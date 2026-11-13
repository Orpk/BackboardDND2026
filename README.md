# BackboardDND2026
Backboard.io Nov 2026

A text-adventure D&D game in pure Python (standard library only, no pip
installs) where an LLM is the Dungeon Master. The DM generates both the
story and simple ASCII scene drawings; whenever the scene changes, the
reply includes a description of the new setting plus an ASCII drawing.

## Game flow
1. **Prologue** - the DM introduces the plot and world, with an ASCII
   drawing of the opening setting.
2. **Character creation scene** - the DM then asks you about your
   character one question at a time (name, ancestry, calling, keepsake,
   personality trait), summarizes the character sheet, and asks you to
   confirm.
3. **The adventure** - play begins with the character you built.

## How to run
```
python backboard_dnd.py
```
**API key** - pick whichever you prefer:
- Put your key on the first non-comment line of **`dnd_api_key.txt`** (recommended)
- Run `python backboard_dnd.py YOUR-KEY`
- Set the `BACKBOARD_API_KEY` environment variable

If none of those are found you'll get a plain visible prompt (the key will
show as you type - that is intended, since hidden `getpass` prompts misbehave
in some Windows terminals). The key is only used in memory and sent to
`app.backboard.io`; it is in `.gitignore` so it won't be committed.

## Commands
`/new` start a fresh game (new thread) - `/model` pick a DM model from
your live `/models` list - `/plot` show the current plot - `/help` - `/quit`

## Editing the plot & constraints
Edit **`dnd_plot.py`** (the general plot, game flow, and constraints).
Changes apply to the next DM reply. Progress (thread id and model choice)
is saved in `.dnd_session.json`, so the adventure continues across runs;
delete that file (or use `/new`) to truly start over.
