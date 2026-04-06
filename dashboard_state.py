"""
dashboard_state.py
File-based shared state between reachy_chat.py and launcher.py.

Since reachy_chat.py and launcher.py run as separate processes,
in-memory state cannot be shared between them. This module uses a
JSON file (dashboard_state.json) as the communication channel.

reachy_chat.py writes to the file.
launcher.py reads from the file.
"""

import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

STATE_FILE = "dashboard_state.json"
_lock      = threading.Lock()

# ── Default State ─────────────────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "version":    0,
        "active":     False,
        "stage":      "clarify",
        "transcript": [],
        "artifacts": {
            "clarify": {
                "challenge_statement": None,
                "focus_question":      None,
            },
            "ideate": {
                "ideas":    [],
                "clusters": [],
            },
            "develop": {
                "plusses":      [],
                "potentials":   [],
                "concerns":     [],
                "action_steps": [],
            },
            "implement": {
                "committed_actions": [],
            },
        }
    }


# ── File I/O ──────────────────────────────────────────────────────────────────

def _read() -> dict:
    """Read state from file. Returns default if file missing or corrupt."""
    if not os.path.exists(STATE_FILE):
        return _default_state()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return _default_state()


def _write(state: dict):
    """Write state to file atomically."""
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except IOError as e:
        logger.error(f"Could not write dashboard state: {e}")


def _bump(state: dict) -> dict:
    """Increment version counter."""
    state["version"] = state.get("version", 0) + 1
    return state


# ── Read API (used by launcher.py) ────────────────────────────────────────────

def get_state() -> dict:
    """Return full state dict — used by Flask polling endpoint."""
    with _lock:
        state = _read()
    return {"version": state.get("version", 0), "state": state}


def get_version() -> int:
    with _lock:
        return _read().get("version", 0)


# ── Write API (used by reachy_chat.py) ────────────────────────────────────────

def set_active(active: bool):
    with _lock:
        state = _read()
        state["active"] = active
        _write(_bump(state))


def set_stage(stage: str):
    with _lock:
        state = _read()
        state["stage"] = stage
        _write(_bump(state))


def add_transcript_entry(role: str, text: str, stage: str):
    with _lock:
        state = _read()
        state["transcript"].append({
            "role":  role,
            "text":  text,
            "stage": stage,
        })
        _write(_bump(state))


def set_artifact(stage: str, key: str, value):
    with _lock:
        state = _read()
        if stage in state["artifacts"] and key in state["artifacts"][stage]:
            state["artifacts"][stage][key] = value
            _write(_bump(state))


def append_artifact(stage: str, key: str, value: str):
    with _lock:
        state = _read()
        if stage in state["artifacts"] and key in state["artifacts"][stage]:
            if isinstance(state["artifacts"][stage][key], list):
                state["artifacts"][stage][key].append(value)
                _write(_bump(state))


def reset():
    """Reset state file to defaults."""
    with _lock:
        _write(_default_state())