---
name: OpenWorkshop
description: A game-focused native desktop workspace for Workshop discovery and downloads.
colors:
  background: "#141619"
  surface: "#1C1F24"
  raised: "#262A31"
  border: "#353B45"
  text: "#F1F3F5"
  text-secondary: "#A7AFBC"
  accent: "#78ABFF"
  accent-hover: "#98BFFF"
  accent-ink: "#101D34"
  accent-dim: "#253752"
  success: "#4EC98A"
  warning: "#E8B84D"
  error: "#E5605C"
typography:
  headline:
    fontFamily: "system-ui"
    fontSize: "23px"
    fontWeight: 650
  title:
    fontFamily: "system-ui"
    fontSize: "16px"
    fontWeight: 650
  body:
    fontFamily: "system-ui"
    fontSize: "13px"
  label:
    fontFamily: "system-ui"
    fontSize: "12px"
  caption:
    fontFamily: "system-ui"
    fontSize: "10px"
    fontWeight: 650
    letterSpacing: "1px"
rounded:
  small: "4px"
  control: "7px"
  navigation: "8px"
  game-card: "9px"
  panel: "10px"
  chip: "13px"
spacing:
  xs: "4px"
  sm: "8px"
  control-x: "10px"
  md: "12px"
  lg: "16px"
  content: "18px"
  section: "20px"
  xl: "24px"
  page: "28px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: "5px 13px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.accent-ink}"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "5px 13px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "5px 13px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.error}"
    rounded: "{rounded.control}"
    padding: "5px 13px"
  input:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  navigation:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.navigation}"
    padding: "6px 10px"
    height: "40px"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.chip}"
    padding: "3px 11px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
---

# Design System: OpenWorkshop

## Overview

**Creative North Star: "A game-focused Workshop workspace"**

The approved direction draws on Thunderstore and Gale: charcoal surfaces, soft
white text, restrained blue actions, and useful game and Workshop artwork. The
interface feels familiar to a player while keeping discovery, installed content,
and transfer recovery easy to read.

The visual system is quiet and practical. A system UI font, packaged monochrome
icons, and compact controls give content the emphasis. Tonal surfaces establish
hierarchy; artwork identifies the game or mod rather than decorating the shell.

**Key Characteristics:**

- Game context stays visible beside a persistent navigation rail.
- Soft white text and restrained blue sit on layered charcoal surfaces.
- Landscape artwork and concise metadata lead discovery.
- Compact controls retain clear labels, keyboard paths, and visible focus.

The native PySide6 implementation is the source of truth. This document records
its reusable tokens; `osw/gui/theme.py`, delegates, and page layouts govern actual
rendering. `docs/mockups/transfer-desk.html` is a gallery of native captures, not a
separate implementation. Surface behavior lives in
`.impeccable/surfaces/desktop.md`; product scope lives in `PRODUCT.md`.

## Colors

The palette uses one blue accent, charcoal neutrals, and semantic state colors.
The frontmatter records the shared palette from `osw/gui/theme.py`.

### Primary

- **Workshop Blue** (`accent`): primary actions, progress, selected outlines, and focus.
- **Open Blue** (`accent-hover`): the primary button's hover state.
- **Blue Ink** (`accent-ink`): text and glyphs on a filled blue action.
- **Quiet Blue** (`accent-dim`): checked controls, selected rows, and navigation.

### Neutral

- **Window Charcoal** (`background`): the workspace floor.
- **Panel Charcoal** (`surface`): navigation, cards, panels, and status strip.
- **Control Charcoal** (`raised`): inputs and secondary controls.
- **Slate Edge** (`border`): control boundaries, separators, and scroll handles.
- **Soft White** (`text`): primary content and labels.
- **Cool Grey** (`text-secondary`): metadata and supplementary explanation.

### Semantic states

- **Success Green** (`success`): completed work and successful feedback.
- **Attention Amber** (`warning`): interrupted work and authentication attention.
- **Failure Red** (`error`): failed work, invalid fields, and destructive actions.

**The Labelled State Rule.** Pair semantic color with visible state text or an
icon and label. A dot or colored border alone cannot explain a transfer state.

## Typography

**Display and Body Font:** the platform's system UI font, inherited from
`QApplication.font()`; `system-ui` is its portable token representation, not a
bundled font dependency.

The hierarchy is compact and readable. Page headings establish place, item titles
identify content, and subdued metadata supports scanning without taking over.

### Hierarchy

- **Headline:** page headings use the headline token.
- **Title:** section headings use the title token.
- **Body:** ordinary widget text uses the body token.
- **Label:** secondary metadata and muted labels use the label token.
- **Caption:** short supporting captions use the caption token sparingly.

Delegate-painted content inherits the same system family and uses Qt point sizes:
Workshop card titles (10.5 pt, demi-bold), metadata (9 pt), game results (9.8 pt),
and their app IDs (8.4 pt). Preserve these units when working in Qt; they are not
pixel values. Paths and identifiers may use the existing system monospace helper.

## Layout

The shell has a left navigation rail, a global header, the active workspace, and
a persistent transfer strip. The full rail is (208 px) wide; below a window width
of (1120 px), it becomes a (64 px) icon rail with tooltips and accessible names.
The default window is (1150 × 740 px), with a minimum of (960 × 640 px).

Browse details appear beside results from (1280 px) window width. Below that,
selecting a mod opens a dismissible details page within the workspace. The strip
uses its narrow form below (1080 px). These are desktop adaptations in Qt logical
pixels, including when the display scale is doubled.

Global header margins are (24 px horizontal, 12 px vertical). Browse and table
workspaces use (18 px) leading content margins; Games and Settings use (28 px).
Common interior gaps use the frontmatter spacing scale. Use local page layouts
for exact margins rather than forcing every workspace into one composition.

Workshop cards adapt their columns to available width using a (244 px) nominal
width, a (210 px) lower sizing bound, and artwork height at (0.56 × card width).
Cards retain two deliberate title lines; the second line elides when necessary.
List mode uses (82 px) rows. Installed table rows are (46 px); Downloads rows are
(62 px). Keep long lists model-backed and independently scrollable. Settings and
the import source column scroll so their bottom controls remain reachable.

## Elevation & Depth

Depth comes from the window, panel, and raised tonal layers plus thin boundaries.
The shared QSS and painted cards do not use drop shadows or decorative gradients.
Keep ordinary surfaces flat; a selected outline and focus border communicate
interaction without simulated physical lift.

**The Tonal Layer Rule.** Establish hierarchy with the existing charcoal layers,
spacing, and selection treatment before adding new surface decoration.

## Shapes

Controls use gently rounded corners; panels and artwork use slightly larger
corners. The frontmatter distinguishes controls, navigation, game cards, panels,
and chips. Thin borders (1 px) clarify control boundaries. Artwork clips to rounded
rectangles (8 px) and crops from the center to fill its landscape frame. Missing
artwork has a quiet monochrome placeholder with a text label.

## Components

### Buttons

Clear and compact. The base control uses the control radius, raised background,
a thin border, and the documented padding. Typical toolbar and navigation
controls occupy roughly (36–40 px); the QSS base has a (26 px) minimum content
height before its padding and border. The inspector's Download action is fixed
at (40 px).

Primary actions use Workshop Blue and Blue Ink; primary hover uses Open Blue.
Secondary controls retain their raised charcoal fill. Ghost controls have a
transparent resting surface. Destructive controls use Failure Red text and
border. Hover and focus change the border; pressed secondary controls use Slate
Edge. Disabled controls use subdued text and panel fill.

### Inputs / Fields

Raised charcoal fields use the control radius and the input token padding. Hover
clarifies the border; focus uses Workshop Blue. Invalid line edits use Failure
Red borders with visible validation feedback. Do not rely on placeholder text to
replace a durable field label. Password and Guard inputs follow session-only
product behavior.

### Navigation

Each destination uses a (40 px) control with a monochrome icon, subdued resting
label, and Quiet Blue selected fill. Hover uses the raised surface. The rail
keeps Games, Browse mods, Installed, and Downloads together, with Settings at the
bottom. The searchable game switcher remains above them. Import links is a global
header action. Compact mode retains names and descriptions for assistive tools.

### Chips

Filter chips use a thin border and capsule corners. Checked chips use Quiet Blue,
a Workshop Blue border, and primary text. Downloads uses labelled filters and
counts; the active state must remain distinguishable through its text and shape.

### Cards / Containers

Workshop cards show a landscape preview, a two-line title, and concise metadata
on Panel Charcoal. Selected and keyboard-focused cards have a Workshop Blue
outline. Game cards use the same landscape emphasis with their own card radius.
List presentation uses the same item model and a smaller preview. General panels
use thin borders and the panel radius; they do not cast shadows.

### Transfer strip and tables

The persistent strip exposes real active-work summaries and opens Downloads.
Tables prioritize the item title, relevant metadata, and current state. Downloads
pairs state labels with progress and exposes selected-job actions in its footer;
Installed pairs the displayed scope and filters with actions targeting that
scope. Essential recovery guidance belongs in visible text, with tooltips as
supplementary explanation.

## Do's and Don'ts

### Do:

- **Do** use the existing charcoal layers and blue accent for hierarchy and interaction.
- **Do** keep game context visible and use real game or Workshop artwork when available.
- **Do** retain visible labels, keyboard focus, and accessible names in compact navigation.
- **Do** preserve usable scrolling and reachable actions at the minimum window size.
- **Do** pair progress and semantic colors with explicit text.

### Don't:

- **Don't** introduce gradients, decorative stock imagery, or a separate display typeface.
- **Don't** treat the HTML screenshot gallery as a replacement for the native Qt source.
- **Don't** use color alone to communicate failure, authentication, completion, or selection.
- **Don't** add launch, profile, or enable/disable controls that imply unsupported mod management.
