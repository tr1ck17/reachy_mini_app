"""
memory_manager.py
Manages rolling session memory — persists the last N conversations to disk
and loads them as context for the LLM at the start of each session.

Session transcripts are appended to a single running file per CPS problem,
identified by a session_id that persists across related sessions.
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

MEMORY_FILE   = "memory.json"
STAGE_FILE    = "stage_state.json"
SESSION_FILE  = "session_id.json"   # tracks the current problem's session ID
SESSIONS_DIR  = "sessions"
MAX_SESSIONS  = 5


# ── Session ID ────────────────────────────────────────────────────────────────

def load_session_id() -> str | None:
    """Load the current problem's session ID from disk."""
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("session_id")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load session ID: {e}")
        return None


def save_session_id(session_id: str):
    """Save the current problem's session ID to disk."""
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"session_id": session_id}, f)
        logger.info(f"Session ID saved: {session_id}")
    except IOError as e:
        logger.error(f"Could not save session ID: {e}")


def new_session_id() -> str:
    """Generate a new unique session ID."""
    return uuid.uuid4().hex[:12]


def clear_session_id():
    """Delete the session ID file (used when starting fresh)."""
    if os.path.exists(SESSION_FILE):
        try:
            os.remove(SESSION_FILE)
            logger.info("Session ID cleared.")
        except IOError as e:
            logger.error(f"Could not clear session ID: {e}")


# ── Load / Save Memory ────────────────────────────────────────────────────────

def load_memory() -> list:
    """
    Load past sessions from disk.
    Returns an empty list if the file doesn't exist or is malformed.
    """
    if not os.path.exists(MEMORY_FILE):
        logger.info("No memory file found — starting fresh.")
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            sessions = json.load(f)
            logger.info(f"Loaded {len(sessions)} past session(s) from memory.")
            return sessions
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not read memory file: {e}. Starting fresh.")
        return []


def save_memory(sessions: list):
    """
    Save sessions to disk, keeping only the most recent MAX_SESSIONS.
    """
    trimmed = sessions[-MAX_SESSIONS:]
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2)
        logger.info(f"Saved {len(trimmed)} session(s) to memory.")
    except IOError as e:
        logger.error(f"Could not save memory file: {e}")


# ── Session Management ────────────────────────────────────────────────────────

def start_session() -> dict:
    """Create a new empty session with a timestamp."""
    return {
        "timestamp": datetime.now().strftime("%A, %B %d %Y at %I:%M %p"),
        "history": []
    }


def append_to_session(session: dict, role: str, content: str):
    """Append a message to the current session's history."""
    session["history"].append({"role": role, "content": content})


def close_session(sessions: list, current_session: dict):
    """
    Append the current session to the sessions list and save to disk.
    Only saves if something was actually said during the session.
    """
    if not current_session.get("history"):
        logger.info("Session was empty — not saving.")
        return
    sessions.append(current_session)
    save_memory(sessions)


# ── Context Building ──────────────────────────────────────────────────────────

def build_history_context(sessions: list) -> list:
    """
    Flatten past sessions into a message list for the LLM.
    Each session is prefixed with a timestamp marker so Reachy
    understands the temporal context of past conversations.
    """
    messages = []
    for session in sessions:
        timestamp = session.get("timestamp", "a previous session")
        messages.append({
            "role": "user",
            "content": f"[Context: the following exchange is from {timestamp}]"
        })
        for msg in session.get("history", []):
            messages.append(msg)
    return messages


# ── Stage Persistence ─────────────────────────────────────────────────────────

def save_stage(stage: str):
    """Save the current CPS stage to disk."""
    try:
        with open(STAGE_FILE, "w", encoding="utf-8") as f:
            json.dump({"stage": stage}, f)
        logger.info(f"Stage saved: {stage}")
    except IOError as e:
        logger.error(f"Could not save stage state: {e}")


def load_stage_state() -> str | None:
    """Load the last saved CPS stage. Returns None if not found."""
    if not os.path.exists(STAGE_FILE):
        return None
    try:
        with open(STAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            stage = data.get("stage")
            logger.info(f"Restored stage: {stage}")
            return stage
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load stage state: {e}")
        return None


# ── Session Export (with merge logic) ────────────────────────────────────────

def _get_transcript_path(session_id: str) -> str:
    """Return the filepath for a session's transcript."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return os.path.join(SESSIONS_DIR, f"session_{session_id}.md")


def export_session(session: dict, session_id: str):
    """
    Export or append a session to its transcript file.

    - If this is the first session for this problem (no existing file),
      creates a new transcript with a header.
    - If the transcript already exists (continuing a problem),
      appends the new session with a clear session break marker.

    All sessions for the same CPS problem are stored in one file,
    giving a complete record of the full journey.
    """
    if not session.get("history"):
        logger.info("Session empty — skipping export.")
        return

    filepath = _get_transcript_path(session_id)
    timestamp = session.get("timestamp", "Unknown")

    try:
        if not os.path.exists(filepath):
            # First session for this problem — create new file with header
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("# Reachy Mini CPS Session\n\n")
                f.write(f"**Started:** {timestamp}\n\n")
                f.write("---\n\n")
                f.write(f"## Session — {timestamp}\n\n")
                _write_messages(f, session["history"])
            logger.info(f"Transcript created: {filepath}")
        else:
            # Continuing session — append with a break marker
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n---\n\n")
                f.write(f"## Session continued — {timestamp}\n\n")
                _write_messages(f, session["history"])
            logger.info(f"Transcript appended: {filepath}")

        print(f"Session transcript saved to {filepath}")

    except IOError as e:
        logger.error(f"Could not export session: {e}")


def _write_messages(f, history: list):
    """Write a list of messages to an open file handle."""
    for msg in history:
        role    = "**You**" if msg["role"] == "user" else "**Reachy**"
        content = msg["content"].strip()
        f.write(f"{role}: {content}\n\n")