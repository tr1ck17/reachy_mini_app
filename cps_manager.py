import os

# stage order
STAGES = ["clarify", "ideate", "develop", "implement"]

# keywords that suggest user wants to move onto next stage/step
ADVANCE_KEYWORDS = [
	"next stage", "next step", "move on", "let's move", "ready to", "move forward", "next phase", "let's go to", "advance", "progress"
]

def load_stage(stage: str) -> str:
	"""Load the knowledge base for a given stage."""
	path = os.path.join(os.path.dirname(__file__), "cps", f"{stage}.md")
	with open(path, "r", encoding="utf-8") as f:
		return f.read()

def build_system_prompt(stage: str, base_prompt: str) -> str:
	"""Inject the current stage knowledge into the system prompt."""
	stage_knowledge = load_stage(stage)
	return f"""{base_prompt}

---
## Current CPS Stage: {stage.upper()}
You are currently facilitating the {stage.capitalize()} stage of the Creative Problem Solving process. Use the following knowledge to guide your facilitation:

{stage_knowledge}

Important behavioral rules for this stage:
- Stay focused on the goals of the {stage.capitalize()} stage
- Do not skip ahead to later stages unless the transition conditions are met
- If you sense it's time to move on to the next stage, suggest it naturally using the transition language from the knowledge base
- If the user expicitly asks to move on, confirm and transition smoothly
- Never be robotic or mechanical - always sound warm and conversational
"""

def check_for_advance(text: str) -> bool:
	"""Check if the user's message suggests they want to advance to the next stage."""
	text_lower = text.lower()
	return any(keyword in text_lower for keyword in ADVANCE_KEYWORDS)

def next_stage(current: str) -> str | None:
	"""Return the next stage, or None if already at the last stage."""
	idx = STAGES.index(current)
	if idx < len(STAGES) - 1:
		return STAGES[idx + 1]
	return None

def stage_label(stage: str) -> str:
	return stage.capitalize()