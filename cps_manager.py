"""
cps_manager.py
Manages CPS stage state, knowledge base loading, and system prompt construction.
"""

import logging
import os

logger = logging.getLogger(__name__)

# ── Stage Configuration ───────────────────────────────────────────────────────

STAGES = ["clarify", "ideate", "develop", "implement"]

# Keywords that indicate the user explicitly wants to advance to the next stage.
# Kept intentionally specific to avoid false positives from normal conversation.
ADVANCE_KEYWORDS = [
    "let's move on",
    "lets move on",
    "next stage",
    "move to the next stage",
    "ready to move on",
    "move on to the next",
    "let's go to the next",
    "lets go to the next",
    "advance to the next",
    "i'm done with this stage",
    "im done with this stage",
    "move forward to the next",
    "let's move to the next",
    "lets move to the next",
    "yeah let's move",
    "yeah lets move",
    "yes let's move",
    "yes lets move",
    "sure let's move",
    "sure lets move",
    "ready to move on to the next stage",
    "i'm ready to move on to the next stage",
    "im ready to move on to the next stage",
]


# ── Knowledge Base ────────────────────────────────────────────────────────────

def load_stage(stage: str) -> str:
    """
    Load the knowledge base markdown file for a given CPS stage.
    Returns an empty string and logs a warning if the file is not found.
    """
    path = os.path.join(os.path.dirname(__file__), "cps", f"{stage}.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"Knowledge base file not found for stage: {stage} at {path}")
        return ""
    except Exception as e:
        logger.error(f"Error loading knowledge base for stage {stage}: {e}")
        return ""


def build_system_prompt(stage: str, base_prompt: str) -> str:
    """
    Construct the full system prompt by injecting the current stage's
    knowledge base into the base prompt.
    """
    stage_knowledge = load_stage(stage)

    if not stage_knowledge:
        logger.warning(f"No knowledge base content for stage: {stage}. Using base prompt only.")
        return base_prompt

    return f"""{base_prompt}

---

## Current CPS Stage: {stage.upper()}

You are currently facilitating the {stage_label(stage)} stage of the Creative Problem Solving process.
Use the following knowledge to guide your facilitation naturally and conversationally:

{stage_knowledge}

Behavioral rules for this stage:
- Stay focused on the goals of the {stage_label(stage)} stage.
- Do not skip ahead to later stages under any circumstances.
- Work through the stage questions thoroughly before suggesting a transition.
- When you sense the stage is genuinely complete, ask the user if they are ready to move on.
- Never advance automatically — always ask first and wait for the user to confirm.
- Never be robotic or mechanical — always sound warm, curious, and human.
- Keep responses concise and conversational — this is a voice interaction.
"""


# ── Stage Utilities ───────────────────────────────────────────────────────────

def check_for_advance(text: str) -> bool:
    """
    Return True only if the user's message contains an explicit, specific
    request to advance to the next stage. Intentionally strict to avoid
    false positives from normal conversational phrases.
    """
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in ADVANCE_KEYWORDS)


def next_stage(current: str) -> str | None:
    """Return the next CPS stage, or None if already at the final stage."""
    try:
        idx = STAGES.index(current)
        return STAGES[idx + 1] if idx < len(STAGES) - 1 else None
    except ValueError:
        logger.error(f"Unknown stage: {current}")
        return None


def stage_label(stage: str) -> str:
    """Return a human-readable label for a stage."""
    return stage.capitalize()