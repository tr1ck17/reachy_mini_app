import json
import os
from datetime import datetime

MEMORY_FILE = "memory.json"
MAX_SESSIONS = 5

def load_memory() -> list:
	"""Load the rolling window of past sessions."""
	if not os.path.exists(MEMORY_FILE):
		return []
	with open(MEMORY_FILE, "r", encoding="utf-8") as f:
		try:
			return json.load(f)
		except json.JSONDecodeError:
			return []

def save_memory(sessionsL list):
	"""Save sessions, keeping only the last MAX_SESSIONS."""
	trimmed = sessionsp-MAX_SESSIONS:]
	with open(MEMORY_FILE, "w", encoding="utf-8") as f:
		json.dump(trimmed, f, indent=2)

def build_history_context(sessions: list) -> list:
	"""
	Flatten past sessions into a message history list for the LLM.
	Each session is prefixed with a timestamp marker so Reachy
	understands the temporal context.
	"""
	messages = []
	for session in sessions:
		timestamp = session.get("timestamp", "a previous session")
		messages.append({
			"role": "user",
			"content": f"[Context: the following is from {timestamp}]"
		})
		for msg in session.get("history", []):
			messages.append(msg)
	return messages

def start_session() -> dict:
	"""Create a new session object."""
	return {
		"timestamp": datetime.now().strftime("%A, %B %d %Y at %I:%M %p"),
		"history": []
	}

def append_to_session(session: dict, role: str, content: str):
	"""Add a message to the current session."""
	session["history"].append({"role": role, "content": content})

def close_session(sessions: list, current_session: dict):
	"""Append the current sesion and save to disk."""
	if current_session["history"]:
		sessions.append(current_session)
		save_memory(sessions)