"""
dashboard_state.py
Shared state module between reachy_chat.py and the Flask launcher/dashboard.
Uses a version counter so the frontend only updates when something changes.
"""

import threading

# ── State ─────────────────────────────────────────────────────────────────────

_lock    = threading.Lock()
_version = 0

_state = {
    "active":         False,       # True once a session is running
    "stage":          "clarify",   # Current CPS stage
    "transcript":     [],          # [{role, text, stage}]
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


# ── Read ──────────────────────────────────────────────────────────────────────

def get_state() -> dict:
    with _lock:
        return {
            "version": _version,
            "state":   _state.copy()
        }


def get_version() -> int:
    with _lock:
        return _version


# ── Write ─────────────────────────────────────────────────────────────────────

def _bump():
    """Increment version counter — signals clients that data changed."""
    global _version
    _version += 1


def set_active(active: bool):
    with _lock:
        _state["active"] = active
        _bump()


def set_stage(stage: str):
    with _lock:
        _state["stage"] = stage
        _bump()


def add_transcript_entry(role: str, text: str, stage: str):
    """Add a line to the live transcript."""
    with _lock:
        _state["transcript"].append({
            "role":  role,   # "user" or "assistant"
            "text":  text,
            "stage": stage,
        })
        _bump()


def set_artifact(stage: str, key: str, value):
    """Set a single artifact value for a stage."""
    with _lock:
        if stage in _state["artifacts"] and key in _state["artifacts"][stage]:
            _state["artifacts"][stage][key] = value
            _bump()


def append_artifact(stage: str, key: str, value: str):
    """Append a value to a list artifact."""
    with _lock:
        if stage in _state["artifacts"] and key in _state["artifacts"][stage]:
            if isinstance(_state["artifacts"][stage][key], list):
                _state["artifacts"][stage][key].append(value)
                _bump()


def reset():
    """Reset all state for a fresh session."""
    global _version
    with _lock:
        _state["active"]    = False
        _state["stage"]     = "clarify"
        _state["transcript"] = []
        _state["artifacts"] = {
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
        _version = 0