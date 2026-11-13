#!/usr/bin/env python3
"""Backboard D&D - a text adventure where the LLM is your Dungeon Master.

Pure standard-library Python (no pip installs). Talks directly to the
Backboard API at https://app.backboard.io/api.

Run:        python backboard_dnd.py
API key:    set BACKBOARD_API_KEY in your environment, or you will be
            prompted at startup.
Commands:   /help  /new  /model  /plot  /quit
"""

import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import dnd_plot  # the editable plot & constraints file

API = "https://app.backboard.io/api"
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".dnd_session.json")

# ANSI colors
GOLD = "\033[93m"
DIM = "\033[90m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Common chat models, tried in order as defaults. No hardcoded model is ever
# sent to the API without first verifying it exists in GET /models - the
# chosen model always comes from that live list.
PREFERRED_MODELS = [
    "openai/gpt-4o",
    "anthropic/claude-3-5-sonnet-20241022",
    "openai/gpt-4.1",
    "google/gemini-2.0-flash",
    "anthropic/claude-3-5-haiku-20241022",
]


def supports_color():
    return sys.stdout.isatty() and os.name == "posix"


def c(text, color):
    return color + text + RESET if supports_color() else text


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
    """Load models from GET /models and pick a default that actually exists."""
    print(c("Loading available models from Backboard...", DIM))
    query = urllib.parse.urlencode({"model_type": "llm", "limit": 500})
    try:
        result = api_call(api_key, "/models?" + query)
    except RuntimeError as e:
        print(c(str(e), RED))
        return None, []
    models = result.get("models", [])
    if not models:
        print(c("No LLM models are available for this API key.", RED))
        return None, []
    model_ids = ["%s/%s" % (m.get("provider"), m.get("name")) for m in models]
    for preferred in PREFERRED_MODELS:
        if preferred in model_ids:
            return preferred, model_ids
    return model_ids[0], model_ids


def choose_model(api_key, current, model_ids):
    """Interactive /model picker over the live model list."""
    print("\nAvailable models (first 100 shown; type the full id):")
    for mid in model_ids[:100]:
        marker = c("  <-- current", GOLD) if mid == current else ""
        print("  " + mid + marker)
    if len(model_ids) > 100:
        print(c("  ... and %d more" % (len(model_ids) - 100), DIM))
    choice = input("\nModel id (empty to keep current): ").strip()
    if not choice:
        return current
    if choice in model_ids:
        return choice
    print(c("That id is not in your model list; keeping %s." % current, RED))
    return current


def system_prompt():
    return (
        "You are the Dungeon Master of a text adventure. You narrate the "
        "story, play every NPC, and adjudicate the player's actions.\n"
        "\nPLOT AND CONSTRAINTS (follow these strictly):\n"
        + dnd_plot.PLOT.strip()
        + "\n\nDM RULES:\n"
        "- Write immersive second-person narration ('You step into...').\n"
        "- Never decide the player's actions, words, or feelings. End each "
        "turn by letting the player act.\n"
        "- Follow the Game Flow in the plot: PROLOGUE first, then the "
        "CHARACTER CREATION SCENE (one question at a time), then the "
        "adventure. Do not skip character creation and do not front-load "
        "all questions at once.\n"
        "- When the scene CHANGES (new location, or a significant shift "
        "within one), you MUST include:\n"
        "  (1) a short vivid description of the new setting, and\n"
        "  (2) a simple ASCII drawing of the scene inside a fenced code "
        "block, e.g.:\n"
        "     ```\n"
        "     [ascii art]\n"
        "     ```\n"
        "  The ASCII art must be one self-contained drawing (max ~20 lines, "
        "max ~60 chars wide) showing the location's layout and key features, "
        "using characters like |, -, +, ~, ^, o, @.\n"
        "- If the scene has NOT changed, reply with plain narration and no "
        "code block.\n"
        "- Wrap dice rolls and mechanical results in *asterisks*, e.g. "
        "*You roll a 14 on DEX - success*.\n"
        "- Keep replies focused: 2-6 short paragraphs, plus the scene block "
        "when it changes."
    )


NEW_GAME_MESSAGE = (
    "Begin a new adventure. Start with the PROLOGUE: a short vivid "
    "introduction to the plot and world described in your instructions, "
    "presenting the opening setting with an ASCII drawing. Then "
    "immediately begin the CHARACTER CREATION SCENE: ask me my first "
    "question (my character's name) and wait for my answer. Remember to "
    "ask one question at a time and wait for my answer each time."
)


def print_reply(text):
    """Print the DM reply; highlight fenced ASCII blocks in gold."""
    inside_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            inside_block = not inside_block
            continue
        if inside_block:
            print(c(line, GOLD))
        else:
            print(line)


def dm_turn(api_key, session, content):
    """Send a message and print the DM's reply. Returns True on success."""
    provider, _, name = session["model"].partition("/")
    payload = {
        "content": content,
        "system_prompt": system_prompt(),
        "llm_provider": provider,
        "model_name": name,
        "stream": False,
    }
    if session.get("thread_id"):
        payload["thread_id"] = session["thread_id"]
    if session.get("assistant_id"):
        payload["assistant_id"] = session["assistant_id"]

    print(c("\n~ The DM ponders your fate... ~\n", DIM))
    try:
        result = api_call(api_key, "/threads/messages", payload)
    except RuntimeError as e:
        print(c(str(e), RED))
        print(c("(Your message was not lost - fix the issue and resend, "
                "or type /model to switch models.)\n", DIM))
        return False

    status = result.get("status")
    if status and status != "COMPLETED":
        print(c("Run ended with status %s (no reply)." % status, RED))
        return False

    if result.get("thread_id"):
        session["thread_id"] = result["thread_id"]
    if result.get("assistant_id"):
        session["assistant_id"] = result["assistant_id"]
    save_session(session)

    print(c("Dungeon Master:", BOLD))
    print_reply(result.get("content", ""))
    print()
    return True


def print_help():
    print("""
Commands:
  /new     abandon the current game and start a fresh one (new thread)
  /model   pick a different DM model (from your live /models list)
  /plot    show the current plot & constraints
  /help    this help
  /quit    leave the game
Anything else is sent to the Dungeon Master.
""")


def main():
    print(c("""
+==============================================+
|         ~  B A C K B O A R D   D & D  ~     |
|       the LLM is your Dungeon Master         |
+==============================================+
""", GOLD))

    api_key = os.environ.get("BACKBOARD_API_KEY", "").strip()
    if not api_key:
        api_key = getpass.getpass("Backboard API key: ").strip()
    if not api_key:
        print(c("No API key provided. Set BACKBOARD_API_KEY and rerun.", RED))
        sys.exit(1)

    session = load_session()

    # Always pick the DM model from the live /models list - never assume a
    # model id is valid for this account.
    default_model, model_ids = pick_model(api_key)
    if default_model is None:
        sys.exit(1)
    stored = session.get("model")
    if stored and stored in model_ids:
        session["model"] = stored
    else:
        session["model"] = default_model
    save_session(session)
    print(c("DM model: %s\n" % session["model"], GOLD))

    if session.get("thread_id"):
        print(c("Continuing your previous adventure. Type /new to start over.\n", DIM))
        print(c("Dungeon Master:", BOLD))
        print(c("(resumed thread - ask the DM to recap: 'Give me a short recap of the story so far.')", DIM))
    else:
        print(c("Starting a new game: prologue, then character creation.\n", DIM))
        dm_turn(api_key, session, NEW_GAME_MESSAGE)

    while True:
        try:
            text = input(c("You > ", DIM)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nFarewell, adventurer.")
            break
        if not text:
            continue
        if text == "/quit":
            print("Farewell, adventurer.")
            break
        elif text == "/help":
            print_help()
        elif text == "/new":
            session["thread_id"] = None
            session["assistant_id"] = None
            save_session(session)
            print(c("New game. The DM will begin with the prologue.\n", DIM))
            dm_turn(api_key, session, NEW_GAME_MESSAGE)
        elif text == "/model":
            session["model"] = choose_model(api_key, session["model"], model_ids)
            save_session(session)
            print(c("DM model is now: %s\n" % session["model"], GOLD))
        elif text == "/plot":
            print(dnd_plot.PLOT.strip())
        else:
            dm_turn(api_key, session, text)


if __name__ == "__main__":
    main()
