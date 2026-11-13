# BackboardDND2026
Backboard.io Nov 2026

A graphical text-adventure D&D game in pure Python (stdlib only) where an
LLM is the Dungeon Master. Running `python backboard_dnd.py` starts a local
server and opens the game in your browser automatically.

## Game flow
1. The UI starts empty except for the DM dialog and the typing area.
2. **Prologue** - the DM introduces the plot and world and switches the
   background image via a `[[SCENE: id]]` tag.
3. **Character creation** - the DM asks one question at a time (name,
   ancestry, calling, keepsake, trait). When you confirm, the DM emits a
   `[[CHARACTER: ...]]` tag: your character appears top-left and the
   Inventory / Map / Settings buttons appear top-right.
4. **The adventure** - the DM narrates, changes backgrounds per scene,
   plays sound effects via `[[SFX: id]]` tags on dramatic moments, and
   updates your inventory via `[[ITEM +: x]]` / `[[ITEM -: x]]` tags.

## How to run
```
python backboard_dnd.py
```
**API key** - put your key on the first non-comment line of
`dnd_api_key.txt` (recommended), pass it as an argument, or set
`BACKBOARD_API_KEY`. Your key stays server-side; the browser never sees it.

## Media (images & audio)
- `media/images/` - background images. `image_prompts.txt` lists every
  scene: `scene_id | image_file | image-generation prompt`. The ids drive
  the DM's scene tags; the prompts are ready to paste into any
  image generator. Missing image files just keep the current background.
- `media/audio/` - sound effects. `sfx_list.txt` lists every sound:
  `sfx_id | audio_file | description`. The DM plays them on events and
  the game plays `ui_click` when buttons are pressed. Missing files are
  skipped silently. Note: browsers block audio before your first click /
  keypress, so the very first sound may be muted - that is normal.

Add, rename or remove scenes/sounds anytime - the server re-reads both
lists at startup and tells the DM which ids exist.

## Commands
Everything you type goes to the DM. The typing box's prompt follows the
DM's current question. While the DM thinks, an animated blade pulses next
to the box.

- `Settings` is visible from the very start; Inventory and Map unlock after
  character creation.
- `Settings -> Save & Quit` writes the full game state (character,
  inventory, scene, complete transcript, thread id and model) to
  `dnd_save.json`. On the next run the UI restores everything and the DM
  continues through its Backboard thread - any model picked at startup can
  pick the story up.
- `Settings -> New Game` starts a fresh thread.

Progress (thread id, model) also persists in `.dnd_session.json`.

## Editing the plot & constraints
Edit **`dnd_plot.py`** - the general plot, game flow, and constraints.
Changes apply to the next DM reply.
