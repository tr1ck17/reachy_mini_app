"""
dashboard_state.py
Shared state module between reachy_chat.py and the Flask launcher/dashboard.
Uses a version counter so the frontend only updates when something changes.
"""

import threading
import time

# ── State ─────────────────────────────────────────────────────────────────────

_lock    = threading.Lock()
_version = 0

_state = {
    "active":         False,
    "stage":          "clarify",
    "transcript":     [],
    "stage_timers":   {         # seconds spent in each stage
        "clarify":   0,
        "ideate":    0,
        "develop":   0,
        "implement": 0,
    },
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

# Timer tracking — not stored in _state directly to avoid lock contention
_stage_start_time = None   # when current stage started
_current_stage    = "clarify"


# ── Read ──────────────────────────────────────────────────────────────────────

def get_state() -> dict:
    with _lock:
        # Include live elapsed time for current stage
        state_copy = dict(_state)
        timers_copy = dict(_state["stage_timers"])
        if _stage_start_time is not None:
            elapsed = time.time() - _stage_start_time
            timers_copy[_current_stage] = (
                _state["stage_timers"].get(_current_stage, 0) + elapsed
            )
        state_copy["stage_timers"] = timers_copy
        state_copy["artifacts"]    = _state["artifacts"]
        return {
            "version": _version,
            "state":   state_copy
        }


def get_version() -> int:
    with _lock:
        return _version


# ── Write ─────────────────────────────────────────────────────────────────────

def _bump():
    global _version
    _version += 1


def set_active(active: bool):
    global _stage_start_time
    with _lock:
        _state["active"] = active
        if active and _stage_start_time is None:
            _stage_start_time = time.time()
        elif not active:
            _commit_stage_time()
        _bump()


def set_stage(stage: str):
    global _stage_start_time, _current_stage
    with _lock:
        # Commit time spent in previous stage
        _commit_stage_time()
        # Start timer for new stage
        _current_stage    = stage
        _stage_start_time = time.time()
        _state["stage"]   = stage
        _bump()


def _commit_stage_time():
    """Commit elapsed time from the current stage timer into state. Must be called with lock held."""
    global _stage_start_time
    if _stage_start_time is not None and _current_stage:
        elapsed = time.time() - _stage_start_time
        _state["stage_timers"][_current_stage] = (
            _state["stage_timers"].get(_current_stage, 0) + elapsed
        )
        _stage_start_time = None


def add_transcript_entry(role: str, text: str, stage: str):
    with _lock:
        _state["transcript"].append({
            "role":  role,
            "text":  text,
            "stage": stage,
        })
        _bump()


def set_artifact(stage: str, key: str, value):
    with _lock:
        if stage in _state["artifacts"] and key in _state["artifacts"][stage]:
            _state["artifacts"][stage][key] = value
            _bump()


def append_artifact(stage: str, key: str, value: str):
    with _lock:
        if stage in _state["artifacts"] and key in _state["artifacts"][stage]:
            if isinstance(_state["artifacts"][stage][key], list):
                _state["artifacts"][stage][key].append(value)
                _bump()


def reset():
    global _version, _stage_start_time, _current_stage
    with _lock:
        _state["active"]    = False
        _state["stage"]     = "clarify"
        _state["transcript"] = []
        _state["stage_timers"] = {
            "clarify":   0,
            "ideate":    0,
            "develop":   0,
            "implement": 0,
        }
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
        _version          = 0
        _stage_start_time = None
        _current_stage    = "clarify"