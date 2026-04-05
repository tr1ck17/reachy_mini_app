"""
launcher.py
Flask server that serves the launcher/dashboard UI and manages
starting/resetting the Reachy Mini CPS Facilitator app.

Endpoints:
  GET  /                    → serves index.html (launcher + dashboard)
  GET  /history             → conversation history viewer
  GET  /api/session-info    → returns previous session info
  POST /api/launch          → launches reachy_chat.py
  POST /api/clear-history   → deletes all memory, stage, session ID, and transcripts
  GET  /api/transcripts     → returns list of all transcript files with metadata
  GET  /api/transcript/<id> → returns full content of a specific transcript
  GET  /api/state           → returns full dashboard state
  GET  /api/poll?since=N    → long-poll: blocks until version > N, then returns state
"""

import glob
import json
import logging
import os
import re
import subprocess
import sys
import time

from flask import Flask, jsonify, request, send_from_directory
import dashboard_state as ds

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=".")

MEMORY_FILE   = "memory.json"
STAGE_FILE    = "stage_state.json"
SESSION_FILE  = "session_id.json"
SESSIONS_DIR  = "sessions"
REACHY_SCRIPT = "reachy_chat.py"
POLL_TIMEOUT  = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_session_info() -> dict:
    info = {
        "has_previous":     False,
        "session_count":    0,
        "last_session":     None,
        "current_stage":    "Clarify",
        "transcript_count": 0,
    }
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                sessions = json.load(f)
            if sessions:
                info["has_previous"]  = True
                info["session_count"] = len(sessions)
                info["last_session"]  = sessions[-1].get("timestamp", "Unknown")
        except (json.JSONDecodeError, IOError):
            pass
    if os.path.exists(STAGE_FILE):
        try:
            with open(STAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            info["current_stage"] = data.get("stage", "clarify").capitalize()
        except (json.JSONDecodeError, IOError):
            pass
    if os.path.exists(SESSIONS_DIR):
        info["transcript_count"] = len(glob.glob(os.path.join(SESSIONS_DIR, "*.md")))
    return info


def get_transcripts() -> list:
    """
    Return a list of all transcript files with metadata.
    Each entry has: id, filename, started, sessions, exchange_count, preview.
    """
    transcripts = []
    if not os.path.exists(SESSIONS_DIR):
        return transcripts

    for filepath in sorted(glob.glob(os.path.join(SESSIONS_DIR, "*.md")), reverse=True):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            filename = os.path.basename(filepath)
            file_id  = filename.replace(".md", "")

            # Extract started date
            started_match = re.search(r"\*\*Started:\*\* (.+)", content)
            started = started_match.group(1).strip() if started_match else "Unknown"

            # Count sessions (## Session markers)
            session_count = len(re.findall(r"^## Session", content, re.MULTILINE))
            if session_count == 0:
                session_count = 1  # old format files

            # Count exchanges
            exchange_count = len(re.findall(r"^\*\*You\*\*:", content, re.MULTILINE))

            # First user message as preview
            preview_match = re.search(r"\*\*You\*\*: (.+?)(?:\n|$)", content)
            preview = preview_match.group(1).strip()[:120] if preview_match else "No content"
            if len(preview) == 120:
                preview += "..."

            transcripts.append({
                "id":             file_id,
                "filename":       filename,
                "started":        started,
                "session_count":  session_count,
                "exchange_count": exchange_count,
                "preview":        preview,
            })
        except Exception as e:
            logger.error(f"Could not read transcript {filepath}: {e}")

    return transcripts


def get_transcript_content(file_id: str) -> str | None:
    """Return the full markdown content of a transcript by ID."""
    filepath = os.path.join(SESSIONS_DIR, f"{file_id}.md")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except IOError as e:
        logger.error(f"Could not read transcript {filepath}: {e}")
        return None


def clear_session_files():
    deleted = []
    for filepath in [MEMORY_FILE, STAGE_FILE, SESSION_FILE]:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                deleted.append(filepath)
            except IOError as e:
                logger.error(f"Could not delete {filepath}: {e}")
    if os.path.exists(SESSIONS_DIR):
        for md_file in glob.glob(os.path.join(SESSIONS_DIR, "*.md")):
            try:
                os.remove(md_file)
                deleted.append(md_file)
            except IOError as e:
                logger.error(f"Could not delete {md_file}: {e}")
    ds.reset()
    return len(deleted)


def clear_session_state_only():
    for filepath in [MEMORY_FILE, STAGE_FILE, SESSION_FILE]:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except IOError as e:
                logger.error(f"Could not delete {filepath}: {e}")
    ds.reset()


def launch_reachy(mode: str) -> bool:
    python = sys.executable
    script = os.path.join(os.path.dirname(__file__), REACHY_SCRIPT)
    if not os.path.exists(script):
        logger.error(f"Script not found: {script}")
        return False
    try:
        env = os.environ.copy()
        env["REACHY_SESSION_MODE"] = mode
        subprocess.Popen(
            ["start", "cmd", "/k", python, script],
            shell=True,
            cwd=os.path.dirname(__file__),
            env=env
        )
        logger.info(f"Launched {REACHY_SCRIPT} (mode={mode}).")
        ds.set_active(True)
        return True
    except Exception as e:
        logger.error(f"Failed to launch {REACHY_SCRIPT}: {e}")
        return False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/history")
def history():
    return send_from_directory(".", "history.html")


@app.route("/api/session-info")
def session_info():
    return jsonify(get_session_info())


@app.route("/api/transcripts")
def transcripts():
    return jsonify(get_transcripts())


@app.route("/api/transcript/<file_id>")
def transcript(file_id: str):
    # Sanitize ID to prevent path traversal
    safe_id = re.sub(r"[^\w\-]", "", file_id)
    content = get_transcript_content(safe_id)
    if content is None:
        return jsonify({"error": "Transcript not found"}), 404
    return jsonify({"id": safe_id, "content": content})


@app.route("/api/launch", methods=["POST"])
def launch():
    data = request.get_json() or {}
    mode = data.get("mode", "continue")
    if mode == "new":
        clear_session_state_only()
    success = launch_reachy(mode)
    if success:
        return jsonify({"status": "launched", "mode": mode})
    return jsonify({"status": "error", "message": "Failed to launch app."}), 500


@app.route("/api/clear-history", methods=["POST"])
def clear_history():
    count = clear_session_files()
    return jsonify({"status": "cleared", "files_deleted": count})


@app.route("/api/state")
def get_state():
    return jsonify(ds.get_state())


@app.route("/api/poll")
def poll():
    try:
        since = int(request.args.get("since", -1))
    except (ValueError, TypeError):
        since = -1
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        if ds.get_version() > since:
            return jsonify(ds.get_state())
        time.sleep(0.2)
    return jsonify(ds.get_state())


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Launcher server starting at http://localhost:5000")
    print("\n=== Reachy Mini Launcher ===")
    print("Open http://localhost:5000 in your browser.\n")
    app.run(host="localhost", port=5000, debug=False, threaded=True)