# Development

[← OpenWorkshop](../README.md)

```bash
git clone https://github.com/adham-samir/openworkshop.git
cd openworkshop
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e '.[dev]'

QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m ruff check osw tests tools
```

Tests use fake SteamCMD processes and fixture metadata: no Steam account, game
installation, API key or live downloads are needed.
