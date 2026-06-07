# DigiTek Lab — Machinima Camera Tool

DigiTek Lab helps you film machinimas in *Welcome to Bloxburg* by building
repeatable camera **executions** out of reusable **macros**, single-use
**actions**, and bundled **core engine macros**, then replaying them as real
keyboard/mouse input to the game.

## Concepts

| Term | What it is | File |
|---|---|---|
| **Macro** | A recorded, reusable sequence of real input (timestamped, screen-normalized). | `data/macros/*.dgtmcr` |
| **Action** | A *parameterized* step (key press, drag, scroll, FOV, wait…). Its template ships with the app; configured copies live inline in an execution. | `server/core/actions/*.dgtact` |
| **Core engine macro** | A bundled, read-only macro used by the engine (reset / first-person / zoom). | `server/core/macros/*.dgtmcr` |
| **Execution** | A **multi-track timeline** of clips (macros / core macros / actions). | `data/executions/*.dgtexec` |

All three are plain JSON under custom extensions. Coordinates are stored
**normalized 0..1** to the recording screen, so playback adapts to resolution.

### Multi-track timeline (clips)

An execution's `timeline` is a flat list of **clips**; each clip places an item at a
position in time on a layer:

| field | meaning |
|---|---|
| `layer` | 0-based track row. Clips on different layers that overlap in time play **simultaneously**. |
| `start` | seconds from the timeline origin |
| `duration` | how long the clip occupies the timeline |
| `trimStart` | seconds skipped from the item's own start (head trim) |

**Resize = trim / hold** (no time-scaling): a clip plays its events at native speed;
make it longer than its content and it idles (holds) to the end, shorter and it
truncates. Drag a clip's **body** to move it in time / to another layer, its **right
edge** to trim or hold the tail, its **left edge** to trim the head. Drop items from
the Action List onto a lane to create clips; **Add layer** adds a track. Legacy
single-list executions migrate to layer 0 on load.

Playback flattens every clip's events into one time-sorted queue, so overlapping
clips run in parallel. **Motion-Controlled** rewinds the camera to its start
position **after** the timeline finishes (see Presets & motion control).

### Bundled engine assets — `server/core/`

```
server/core/
 ├── macros/     core engine macros   (*.dgtmcr)
 └── actions/    action templates     (*.dgtact)
```

Action templates (`.dgtact`) are the single source of truth for the palette: each
defines its `actionType`, `name`, `icon`, `order`, `defaults`, editor `fields`
(with `widget` hints), and an optional `pick` descriptor. The UI loads them at boot
via `dgt_list_actions`; the Python `player` compiles each `actionType` to events.
Edit the `.dgtact` files to change actions — the frontend has only a fallback copy.

### Screen picker overlay

Actions with coordinates carry a `pick` descriptor (`{"mode":"point"}` or
`{"mode":"line"}`). In the action editor, **Pick on screen** opens a full-screen,
transparent overlay (`ui/modals/overlay.html`) where you click a point or drag a
line; the captured normalized coordinates fill the fields. The overlay uses the
engine's `fullscreen="true" transparent="true"` modal support.

## Presets & motion control

- **FOV** action: zooms the camera fully **out** first (for a consistent start),
  then scrolls **in** to a defined point.
- **Motion Controlled** toggle (toolbar): when ON, after the execution finishes it
  **plays backward** — the camera pan (relative right-drag motion) and zoom (scroll)
  logged during the run are replayed in reverse order, inverted, with mirrored
  timing, retracing the camera to its starting position. This lets you re-run the
  exact same move, e.g. to film a clean plate. When OFF, the camera stays where the
  execution ends. (Backward play covers the reliable camera operations — Mouse Drag
  actions and scroll/FOV; it does not reverse character-movement keys or recorded
  absolute-cursor macros.)

## Core engine macros

`zoom_out_max` and `first_person` are deterministic scroll bursts. `reset_character`
is **game-specific** and ships as a *calibratable placeholder* (`Esc → R → Enter`).
If it doesn't match your setup, record your own and it can replace the default.

> Scroll convention (matches Roblox): wheel **down** (`dy < 0`) zooms **out**,
> wheel **up** (`dy > 0`) zooms **in** toward first person.

## Toolbar

Play/Pause · Stop · Record · New / Save / Open / Export execution · **Motion
Controlled** toggle · execution name. The Action List (right) holds the Actions
palette, your Saved Macros, and the Core Engine Macros — click to append or drag
onto the timeline to insert.

## Global hotkeys

While recording or playing, focus is on Roblox, not the app. Use:

- **F8** — stop recording
- **F9** — stop playback

## Dependency

Recording and playback use [`pynput`](https://pypi.org/project/pynput/). It is
installed by `scripts/setup.py` for development and bundled into the Standalone
build by `scripts/build.py`. If it is missing, the UI still loads and shows a
warning; record/play are disabled until it is installed.
