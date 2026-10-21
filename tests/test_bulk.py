import threading
from unittest.mock import Mock

import pytest

from osw import bulk, steam_api
from osw.models import WorkshopItem
from osw.net import NetError


def row(n, **values):
    return {
        "publishedfileid": str(n),
        "consumer_app_id": 10,
        "title": f"Mod {n}",
        "result": 1,
        "children": [],
        **values,
    }


def test_nested_collections_cycles_and_shared_dependencies(monkeypatch):
    metadata = {
        1: row(1, filetype=2),
        2: row(2, filetype=2),
        3: row(3, children=[{"publishedfileid": "5"}]),
        4: row(4, children=[5]),
        5: row(5, children=[3]),
    }
    monkeypatch.setattr(
        bulk, "get_published_files", lambda ids, cancel: {n: metadata[n] for n in ids}
    )
    monkeypatch.setattr(
        bulk, "get_collection_children", lambda n, cancel: {1: [2, 3, 4], 2: [1, 3]}[n]
    )
    resolved = bulk.resolve_downloads(["1", "3"], include_dependencies=True)
    assert [i.publishedfileid for i in resolved.items] == [3, 4, 5]
    assert resolved.collections == 2
    assert resolved.dependencies == {3, 5}
    assert resolved.duplicates >= 3
    assert not resolved.issues


def test_partial_failures_and_appid_hint(monkeypatch):
    monkeypatch.setattr(
        bulk,
        "get_published_files",
        lambda ids, cancel: {1: row(1), 2: row(2, result=9), 3: row(3, consumer_app_id=0)},
    )
    result = bulk.resolve_downloads("1\n2\n3\nhttps://evil.example/?id=4")
    assert [i.publishedfileid for i in result.items] == [1]
    assert len(result.issues) == 3
    result = bulk.resolve_downloads(["1", "3"], appid_hint=99)
    assert [i.appid for i in result.items] == [10, 99]


def test_dependencies_are_opt_in_and_cancel_is_honored(monkeypatch):
    get = Mock(return_value={1: row(1, children=[2])})
    monkeypatch.setattr(bulk, "get_published_files", get)
    result = bulk.resolve_downloads(["1"])
    assert len(result.items) == 1 and not result.dependencies
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        bulk.resolve_downloads(["1"], cancel=cancel)


def test_dependency_lookup_failure_retains_root(monkeypatch):
    item = row(1)
    del item["children"]
    monkeypatch.setattr(bulk, "get_published_files", lambda *a: {1: item})
    monkeypatch.setattr(bulk, "get_item_details", Mock(side_effect=NetError("offline")))
    result = bulk.resolve_downloads(["1"], include_dependencies=True)
    assert len(result.items) == len(result.issues) == 1


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://steamcommunity.com/sharedfiles/filedetails?id=123&searchtext=x", (None, [123])),
        ("https://steamcommunity.com/workshop/filedetails/?foo=x&id=123", (None, [123])),
        ("https://steamcommunity.com/app/10", (10, [])),
        ("https://store.steampowered.com/app/10/Game/", (10, [])),
        ("https://evil.example/?id=123", (None, [])),
        ("https://steamcommunity.com.evil.example/sharedfiles/filedetails/?id=123", (None, [])),
        ("10", (10, [])),
        ("0", (None, [])),
    ],
)
def test_url_resolution(url, expected):
    assert steam_api.resolve_ids(url) == expected


def test_ssr_attribute_order_empty_results_and_schema_changes(monkeypatch):
    page = '<script id=\'valve-ssr-data\' type=\'application/json\'>{"loaderData": "{\\"total_count\\":0,\\"results\\":[]}"}</script>'
    monkeypatch.setattr(steam_api.http, "text", lambda *a, **kw: page)
    assert steam_api.browse_workshop(10) == ([], 0, 0)
    with pytest.raises(NetError, match="invalid SSR"):
        steam_api._extract_ssr_blob('<script id="valve-ssr-data">{oops</script>')
    monkeypatch.setattr(
        steam_api.http, "text", lambda *a, **kw: '<script id="valve-ssr-data">{}</script>'
    )
    with pytest.raises(NetError, match="format changed"):
        steam_api.browse_workshop(10)


def test_structured_metadata_posts_without_api_key(monkeypatch):
    post = Mock(
        return_value={
            "response": {"publishedfiledetails": [row(1, filename="mod.gma", file_size="1")]}
        }
    )
    monkeypatch.setattr(steam_api.http, "json", post)
    assert steam_api.get_published_files([1, 1])[1]["title"] == "Mod 1"
    kwargs = post.call_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["data"] == {"itemcount": 1, "publishedfileids[0]": 1}


def test_real_collection_response_without_file_type_is_detected(monkeypatch):
    metadata = row(1, file_size="0", filename="")
    metadata.pop("children")
    post = Mock(
        side_effect=[
            {"response": {"publishedfiledetails": [metadata]}},
            {
                "response": {
                    "collectiondetails": [
                        {
                            "publishedfileid": "1",
                            "result": 1,
                            "children": [{"publishedfileid": "2"}],
                        }
                    ]
                }
            },
        ]
    )
    monkeypatch.setattr(steam_api.http, "json", post)
    result = steam_api.get_published_files([1])
    assert result[1]["file_type"] == 2
    assert result[1]["_collection_children"] == [2]
    assert post.call_args.args[0] == steam_api.COLLECTION_DETAILS


def test_failed_collection_detection_is_reported_not_downloaded(monkeypatch):
    monkeypatch.setattr(
        bulk, "get_published_files", lambda *a: {1: row(1, _collection_error="offline")}
    )
    result = bulk.resolve_downloads(["1"])
    assert not result.items
    assert "Collection lookup failed" in result.issues[0].message


def test_models_accept_both_children_shapes_and_keep_exact_ids():
    item = WorkshopItem.from_browse_dict(
        {
            "publishedfileid": "76561198012345678",
            "children": ["2", {"publishedfileid": "3"}, None],
            "tags": ["Maps", {"tag": "Test"}],
            "star_rating": "invalid",
        }
    )
    assert item.publishedfileid == 76561198012345678
    assert item.children == [2, 3]
    assert item.tags == ["Maps", "Test"]


def test_required_items_parser_keeps_all_nested_links():
    parser = steam_api._RequiredLinks()
    parser.feed(
        '<div id="RequiredItems"><a href="https://steamcommunity.com/sharedfiles/filedetails/?id=1">'
        '<div><img src="x">One</div></a><a href="https://steamcommunity.com/sharedfiles/filedetails/?id=2">'
        '<span>Two</span></a></div><a href="https://steamcommunity.com/sharedfiles/filedetails/?id=3">Other</a>'
    )
    assert parser.items == [(1, "One"), (2, "Two")]
