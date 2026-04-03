"""
memory_manager.py
Manages rolling session memory — persists the last N conversations to disk
and loads them as context for the LLM at the start of each session.
"""

import json
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

MEMORY_FILE  = "memory.json"
STAGE_FILE   = "stage_state.json"
SESSIONS_DIR = "sessions"
MAX_SESSIONS = 5


# ── Load / Save ───────────────────────────────────────────────────────────────

def load_memory() -> list:
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
    trimmed = sessions[-MAX_SESSIONS:]
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2)
        logger.info(f"Saved {len(trimmed)} session(s) to memory.")
    except IOError as e:
        logger.error(f"Could not save memory file: {e}")


# ── Session Management ────────────────────────────────────────────────────────

def start_session() -> dict:
    return {
        "timestamp": datetime.now().strftime("%A, %B %d %Y at %I:%M %p"),
        "history": []
    }


def append_to_session(session: dict, role: str, content: str):
    session["history"].append({"role": role, "content": content})


def close_session(sessions: list, current_session: dict):
    if not current_session.get("history"):
        logger.info("Session was empty — not saving.")
        return
    sessions.append(current_session)
    save_memory(sessions)


# ── Context Building ──────────────────────────────────────────────────────────

def build_history_context(sessions: list) -> list:
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
    try:
        with open(STAGE_FILE, "w", encoding="utf-8") as f:
            json.dump({"stage": stage}, f)
        logger.info(f"Stage saved: {stage}")
    except IOError as e:
        logger.error(f"Could not save stage state: {e}")


def load_stage_state() -> str | None:
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


# ── Session Export ────────────────────────────────────────────────────────────

def export_session(session: dict):
    if not session.get("history"):
        logger.info("Session empty — skipping export.")
        return

    os.makedirs(SESSIONS_DIR, exist_ok=True)

    timestamp = session.get("timestamp", "unknown")
    safe_name = re.sub(r'[^\w\s-]', '', timestamp)
    safe_name = re.sub(r'\s+', '_', safe_name).strip()
    filepath  = os.path.join(SESSIONS_DIR, f"{safe_name}.md")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# Reachy Mini CPS Session\n")
            f.write(f"**Date:** {timestamp}\n\n")
            f.write("---\n\n")
            for msg in session["history"]:
                role    = "**You**" if msg["role"] == "user" else "**Reachy**"
                content = msg["content"].strip()
                f.write(f"{role}: {content}\n\n")
        logger.info(f"Session exported to {filepath}")
        print(f"Session transcript saved to {filepath}")
    except IOError as e:
        logger.error(f"Could not export session: {e}")