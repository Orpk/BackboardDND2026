#!/usr/bin/env python3
"""Backboard D&D - a graphical text adventure where the LLM is the DM.

Runs a local web server (stdlib only, no pip installs) and opens the game
in your browser. Talks to the Backboard API at https://app.backboard.io/api
server-side, so the API key never reaches the browser.

Run:        python backboard_dnd.py
API key:    put your key on the first line of dnd_api_key.txt, or set
            BACKBOARD_API_KEY, or pass it as an argument:
            python backboard_dnd.py YOUR-KEY

Scenes and sound effects are driven by two editable text files:
            media/images/image_prompts.txt   (scene id | file | prompt)
            media/audio/sfx_list.txt         (sfx id | file | description)
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler

import dnd_plot  # the editable plot & constraints file

BASE = os.path.dirname(os.path.abspath(__file__))
API = "https://app.backboard.io/api"
SESSION_FILE = os.path.join(BASE, ".dnd_session.json")
KEY_FILE = os.path.join(BASE, "dnd_api_key.txt")
SAVE_FILE = os.path.join(BASE, "dnd_save.json")
IMAGE_PROMPTS_FILE = os.path.join(BASE, "media", "images", "image_prompts.txt")
SFX_LIST_FILE = os.path.join(BASE, "media", "audio", "sfx_list.txt")

# Common chat models, tried in order as defaults. No model id is ever sent
# to the API without first verifying it exists in GET /models.
PREFERRED_MODELS = [
    "openai/gpt-4o",
    "anthropic/claude-3-5-sonnet-20241022",
    "openai/gpt-4.1",
    "google/gemini-2.0-flash",
    "anthropic/claude-3-5-haiku-20241022",
]


def read_api_key():
    """Resolve the Backboard API key.

    Order: dnd_api_key.txt file, BACKBOARD_API_KEY env var, command-line
    argument, then a plain *visible* input prompt (getpass is deliberately
    not used - hidden prompts misbehave in some Windows terminals).
    """
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    key = os.environ.get("BACKBOARD_API_KEY", "").strip()
    if key:
        return key
    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    print("No API key found.")
    print("Recommended: paste your key on the first line of dnd_api_key.txt")
    print("(or run: python backboard_dnd.py YOUR-KEY, or set BACKBOARD_API_KEY).")
    try:
        return input("Backboard API key (typed visibly): ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def api_call(api_key, path, payload=None):
    """GET or POST to the Backboard API, returning parsed JSON."""
    url = API + path
    data = None
    headers = {"X-API-Key": api_key}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        detail = body.get("detail") or body.get("error") or str(e)
        raise RuntimeError("API error (HTTP %s): %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("Network error: %s" % e.reason)


def load_session():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_session(session):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2)


def pick_model(api_key):
    """Pick the DM model from the live GET /models list only."""
    query = urllib.parse.urlencode({"model_type": "llm", "limit": 500})
    result = api_call(api_key, "/models?" + query)
    models = result.get("models", [])
    if not models:
        raise RuntimeError("No LLM models are available for this API key.")
    model_ids = ["%s/%s" % (m.get("provider"), m.get("name")) for m in models]
    for preferred in PREFERRED_MODELS:
        if preferred in model_ids:
            return preferred
    return model_ids[0]


def parse_media_list(path):
    """Parse 'id | file | description' lines (comments with #, blank lines ok)."""
    entries = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    entries[parts[0].lower()] = {
                        "file": parts[1],
                        "description": parts[2],
                    }
    except OSError:
        pass
    return entries


def load_media():
    scenes = parse_media_list(IMAGE_PROMPTS_FILE)
    sfx = parse_media_list(SFX_LIST_FILE)
    return scenes, sfx


def system_prompt(scenes, sfx):
    scene_lines = "\n".join(
        "  - %s (%s)" % (sid, scenes[sid]["description"])
        for sid in sorted(scenes))
    sfx_lines = "\n".join(
        "  - %s (%s)" % (sid, sfx[sid]["description"])
        for sid in sorted(sfx))
    return (
        "You are the Dungeon Master of a graphical text adventure. You "
        "narrate the story, play every NPC, and adjudicate the player's "
        "actions. The player sees your narration in a dialog box; the game "
        "renders backgrounds, sounds, the character panel, and the inventory "
        "for you based on special tags you emit.\n"
        "\nPLOT AND CONSTRAINTS (follow these strictly):\n"
        + dnd_plot.PLOT.strip()
        + "\n\nTAG PROTOCOL (obey exactly):\n"
        "- When the scene CHANGES (new location, or a significant shift "
        "within one), you MUST emit a scene tag on its own line, choosing "
        "the best-fitting scene id from AVAILABLE SCENES below:\n"
        "     [[SCENE: scene_id]]\n"
        "  and also write a short vivid description of the new setting "
        "in your narration. Never draw ASCII art, and never emit a scene "
        "tag when the scene has not changed.\n"
        "- For dramatic moments (doors opening, combat, discovery, danger), "
        "you may add a sound-effect tag on its own line:\n"
        "     [[SFX: sfx_id]]\n"
        "  using only ids from AVAILABLE SOUNDS below. At most one SFX tag "
        "per reply.\n"
        "- When the player confirms their character, emit exactly one "
        "character tag on its own line:\n"
        "     [[CHARACTER: Name | ancestry | calling | keepsake item | "
        "personality trait]]\n"
        "  This makes the character panel and the game buttons appear.\n"
        "- Whenever the player gains or loses an item, emit an item tag on "
        "its own line:\n"
        "     [[ITEM +: item name]]   or   [[ITEM -: item name]]\n"
        "- Tags are stripped from what the player reads, so never explain a "
        "tag inside your narration and never rely on tag text as prose.\n"
        "\nDM RULES:\n"
        "- Write immersive second-person narration ('You step into...').\n"
        "- Never decide the player's actions, words, or feelings. End each "
        "turn by letting the player act.\n"
        "- Follow the Game Flow in the plot: PROLOGUE first, then the "
        "CHARACTER CREATION SCENE (one question at a time), then the "
        "adventure. Do not skip character creation and do not front-load "
        "all questions at once.\n"
        "- Wrap dice rolls and mechanical results in *asterisks*, e.g. "
        "*You roll a 14 on DEX - success*.\n"
        "- Keep replies focused: 2-6 short paragraphs.\n"
        + ("\nAVAILABLE SCENES (scene ids you may use with [[SCENE:]]):\n"
           + scene_lines + "\n" if scenes else "")
        + ("\nAVAILABLE SOUNDS (sfx ids you may use with [[SFX:]]):\n"
           + sfx_lines if sfx else "")
    )


NEW_GAME_MESSAGE = (
    "Begin a new adventure. Start with the PROLOGUE: a short vivid "
    "introduction to the plot and world described in your instructions, "
    "presenting the opening setting and emitting the matching [[SCENE:]] "
    "tag. Then immediately begin the CHARACTER CREATION SCENE: ask me my "
    "first question (my character's name) and wait for my answer. Remember "
    "to ask one question at a time and wait for my answer each time."
)


class Game:
    def __init__(self, api_key, model, scenes, sfx):
        self.api_key = api_key
        self.model = model
        self.scenes = scenes
        self.sfx = sfx

    def dm_turn(self, content, thread_id=None, assistant_id=None):
        provider, _, name = self.model.partition("/")
        payload = {
            "content": content,
            "system_prompt": system_prompt(self.scenes, self.sfx),
            "llm_provider": provider,
            "model_name": name,
            "stream": False,
        }
        if thread_id:
            payload["thread_id"] = thread_id
        if assistant_id:
            payload["assistant_id"] = assistant_id
        result = api_call(self.api_key, "/threads/messages", payload)
        status = result.get("status")
        if status and status != "COMPLETED":
            raise RuntimeError("Run ended with status %s." % status)
        return result


class Handler(SimpleHTTPRequestHandler):
    game = None  # set by main()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def log_message(self, fmt, *args):
        pass  # keep the console quiet; errors still print via exceptions

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return {}

    def do_GET(self):
        if self.path == "/api/state":
            session = load_session()
            self._json({
                "active": bool(session.get("thread_id")),
                "model": self.game.model if self.game else None,
            })
        elif self.path == "/api/manifest":
            self._json({"scenes": self.game.scenes, "sfx": self.game.sfx})
        elif self.path == "/api/save":
            state = {}
            try:
                with open(SAVE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (OSError, ValueError):
                pass
            self._json(state if state else {})
        else:
            super().do_GET()

    def do_POST(self):
        if not self.game:
            self._json({"content": "Server not ready.", "error": True}, 503)
            return
        body = self._body()
        session = load_session()
        try:
            if self.path == "/api/new":
                result = self.game.dm_turn(NEW_GAME_MESSAGE)
                session["thread_id"] = result.get("thread_id")
                session["assistant_id"] = result.get("assistant_id")
                save_session(session)
                self._json({"content": result.get("content", "")})
            elif self.path == "/api/send":
                content = (body.get("content") or "").strip()
                if not content:
                    self._json({"content": "", "error": "empty message"}, 400)
                    return
                result = self.game.dm_turn(
                    content,
                    thread_id=session.get("thread_id"),
                    assistant_id=session.get("assistant_id"))
                if result.get("thread_id"):
                    session["thread_id"] = result["thread_id"]
                if result.get("assistant_id"):
                    session["assistant_id"] = result["assistant_id"]
                save_session(session)
                self._json({"content": result.get("content", "")})
            elif self.path == "/api/save":
                # Full player state: character, inventory, scene and the
                # complete transcript, so any DM model can pick the game
                # back up next session.
                state = body.get("state") or {}
                state["thread_id"] = session.get("thread_id")
                state["assistant_id"] = session.get("assistant_id")
                state["model"] = self.game.model
                with open(SAVE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
                self._json({"saved": True})
            else:
                self._json({"content": "not found", "error": True}, 404)
        except RuntimeError as e:
            self._json({"content": "", "error": str(e)}, 502)


def main():
    print("Backboard D&D - graphical edition")
    api_key = read_api_key()
    if not api_key:
        print("No API key provided. Put it in dnd_api_key.txt and rerun.")
        sys.exit(1)

    try:
        model = pick_model(api_key)
    except RuntimeError as e:
        print("Could not pick a DM model: %s" % e)
        sys.exit(1)
    print("DM model: %s" % model)

    scenes, sfx = load_media()
    print("Loaded %d scene ids and %d sound ids from the media folders."
          % (len(scenes), len(sfx)))

    Handler.game = Game(api_key, model, scenes, sfx)

    port = 8765
    server = None
    for attempt in range(10):
        try:
            server = HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    if server is None:
        print("Could not find a free local port.")
        sys.exit(1)

    url = "http://127.0.0.1:%d/" % port
    print("Serving the game at %s (Ctrl+C to stop)" % url)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFarewell, adventurer.")


if __name__ == "__main__":
    main()
