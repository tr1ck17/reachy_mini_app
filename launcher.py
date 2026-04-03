"""
launcher.py
A minimal Flask server that serves the launcher UI and manages
starting/resetting the Reachy Mini CPS Facilitator app.

Usage:
    uv run launcher.py
Then open http://localhost:5000 in your browser.
"""

import json
import logging
import os
import subprocess
import sys

from flask import Flask, jsonify, request, send_from_directory

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── App Setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=".")

MEMORY_FILE     = "memory.json"
STAGE_FILE      = "stage_state.json"
REACHY_SCRIPT   = "reachy_chat.py"

# Track the running process
_process = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_session_info() -> dict:
    """
    Read memory and stage state files and return a summary
    for display in the launcher UI.
    """
    info = {
        "has_previous": False,
        "session_count": 0,
        "last_session": None,
        "current_stage": "Clarify",
    }

    # Load memory
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                sessions = json.load(f)
            if sessions:
                info["has_previous"]  = True
                info["session_count"] = len(sessions)
                info["last_session"]  = sessions[-1].get("timestamp", "Unknown")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not read memory file: {e}")

    # Load stage
    if os.path.exists(STAGE_FILE):
        try:
            with open(STAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            info["current_stage"] = data.get("stage", "clarify").capitalize()
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not read stage file: {e}")

    return info


def clear_session():
    """Delete memory and stage state files to start fresh."""
    for filepath in [MEMORY_FILE, STAGE_FILE]:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Cleared: {filepath}")
            except IOError as e:
                logger.error(f"Could not delete {filepath}: {e}")


def launch_reachy():
    """Launch reachy_chat.py in a new terminal window."""
    global _process
    python = sys.executable
    script = os.path.join(os.path.dirname(__file__), REACHY_SCRIPT)

    if not os.path.exists(script):
        logger.error(f"Script not found: {script}")
        return False

    try:
        # Launch in a new terminal window on Windows
        _process = subprocess.Popen(
            ["start", "cmd", "/k", python, script],
            shell=True,
            cwd=os.path.dirname(__file__)
        )
        logger.info(f"Launched {REACHY_SCRIPT} in new terminal.")
        return True
    except Exception as e:
        logger.error(f"Failed to launch {REACHY_SCRIPT}: {e}")
        return False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the launcher HTML page."""
    return send_from_directory(".", "index.html")


@app.route("/api/session-info")
def session_info():
    """Return current session info as JSON."""
    return jsonify(get_session_info())


@app.route("/api/launch", methods=["POST"])
def launch():
    """
    Launch the Reachy app.
    Accepts JSON body: { "mode": "continue" | "new" }
    """
    data = request.get_json() or {}
    mode = data.get("mode", "continue")

    if mode == "new":
        clear_session()
        logger.info("Starting new session — previous data cleared.")

    success = launch_reachy()

    if success:
        return jsonify({"status": "launched", "mode": mode})
    else:
        return jsonify({"status": "error", "message": "Failed to launch app."}), 500


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Launcher server starting at http://localhost:5000")
    print("\n=== Reachy Mini Launcher ===")
    print("Open http://localhost:5000 in your browser.\n")
    app.run(host="localhost", port=5000, debug=False)