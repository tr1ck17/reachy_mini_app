"""
behaviors.py
Natural movement library for Reachy Mini CPS Facilitator.

Provides categorized pose/animation sets for different conversational moments:
- Thinking poses (question vs statement)
- Talking animations (while Reachy speaks)
- Listening poses (while user speaks)
- Mood reactions (happy, surprised, neutral)
- Idle animations (while waiting)

All movements are designed to feel natural and unhurried.
Durations are kept gentle — nothing jerky or robotic.
"""

import random
import time
import threading
import logging

from reachy_mini.utils import create_head_pose

logger = logging.getLogger(__name__)


# ── Thinking Poses (triggered while LLM generates) ───────────────────────────
# Used when user asked a question — more contemplative, upward/sideways gazes

THINKING_QUESTION_POSES = [
    # Look up and to the left — classic "hmm" pose
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=12, roll=-10, degrees=True, mm=True), duration=1.2),
    ),
    # Look up slightly, tilt right — curious dog style
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=8, roll=14, degrees=True, mm=True), duration=1.0),
    ),
    # Look down and left — deep in thought
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=-6, roll=-12, degrees=True, mm=True), duration=1.1),
    ),
    # Tilt head to the right, look slightly up
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=6, roll=18, degrees=True, mm=True), duration=1.0),
    ),
    # Look straight up — sky gazer
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=15, mm=True), duration=1.0),
    ),
]

# Used when user made a statement — more grounded, forward/downward reflection
THINKING_STATEMENT_POSES = [
    # Look slightly down — processing, reflective
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=-8, mm=True), duration=1.1),
    ),
    # Gentle tilt left — attentive lean
    lambda mini: (
        mini.goto_target(head=create_head_pose(roll=-10, degrees=True), duration=1.0),
    ),
    # Look down and right — processing what was said
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=-5, roll=10, degrees=True, mm=True), duration=1.2),
    ),
    # Slight bow — acknowledging
    lambda mini: (
        mini.goto_target(head=create_head_pose(z=-10, mm=True), duration=0.9),
    ),
    # Neutral tilt right
    lambda mini: (
        mini.goto_target(head=create_head_pose(roll=12, degrees=True), duration=1.0),
    ),
]


# ── Talking Animations (while Reachy speaks) ──────────────────────────────────
# Gentle rhythmic movements that make speech feel embodied

def talking_animation(mini, stop_event: threading.Event):
    """
    Runs in a background thread while Reachy is speaking.
    Gently bobs and sways the head to match natural speech rhythm.
    """
    moves = [
        # Gentle forward nod
        lambda: (
            mini.goto_target(head=create_head_pose(z=-4, mm=True), duration=0.6),
            mini.goto_target(head=create_head_pose(), duration=0.5),
        ),
        # Slight left lean then back
        lambda: (
            mini.goto_target(head=create_head_pose(roll=-6, degrees=True), duration=0.7),
            mini.goto_target(head=create_head_pose(), duration=0.6),
        ),
        # Slight right lean then back
        lambda: (
            mini.goto_target(head=create_head_pose(roll=6, degrees=True), duration=0.7),
            mini.goto_target(head=create_head_pose(), duration=0.6),
        ),
        # Small look left then return
        lambda: (
            mini.goto_target(head=create_head_pose(roll=-8, degrees=True), duration=0.8),
            mini.goto_target(head=create_head_pose(), duration=0.7),
        ),
        # Small look right then return
        lambda: (
            mini.goto_target(head=create_head_pose(roll=8, degrees=True), duration=0.8),
            mini.goto_target(head=create_head_pose(), duration=0.7),
        ),
        # Subtle up nod — emphasizing a point
        lambda: (
            mini.goto_target(head=create_head_pose(z=5, mm=True), duration=0.5),
            mini.goto_target(head=create_head_pose(), duration=0.5),
        ),
    ]

    while not stop_event.is_set():
        try:
            move = random.choice(moves)
            move()
            stop_event.wait(timeout=random.uniform(1.0, 2.0))
        except Exception:
            break

    # Return to neutral when done
    try:
        mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=0.5)
    except Exception:
        pass


# ── Listening Pose (while user is recording) ─────────────────────────────────
# Attentive, leaning-in postures

LISTENING_POSES = [
    # Lean in slightly — attentive
    lambda mini: mini.goto_target(
        head=create_head_pose(z=3, mm=True), duration=0.8
    ),
    # Tilt head left — curious listening
    lambda mini: mini.goto_target(
        head=create_head_pose(roll=-8, degrees=True), duration=0.8
    ),
    # Tilt head right — interested
    lambda mini: mini.goto_target(
        head=create_head_pose(roll=8, degrees=True), duration=0.8
    ),
    # Slight forward lean — engaged
    lambda mini: mini.goto_target(
        head=create_head_pose(z=5, roll=-5, degrees=True, mm=True), duration=0.9
    ),
    # Neutral upright — calm attention
    lambda mini: mini.goto_target(
        head=create_head_pose(), duration=0.6
    ),
]


# ── Mood Reactions ─────────────────────────────────────────────────────────────

def react_happy(mini):
    """Excited antenna wiggle + perky head lift."""
    try:
        mini.goto_target(head=create_head_pose(z=8, mm=True), antennas=[0.7, 0.7], duration=0.3)
        mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=0.4)
        mini.goto_target(antennas=[0.5, 0.5], duration=0.25)
        mini.goto_target(antennas=[0, 0], duration=0.3)
    except Exception as e:
        logger.warning(f"React happy error: {e}")


def react_surprised(mini):
    """Sharp head jolt up + antenna spike."""
    try:
        mini.goto_target(head=create_head_pose(z=16, mm=True), antennas=[0.9, 0.9], duration=0.25)
        mini.goto_target(head=create_head_pose(z=8, mm=True), duration=0.3)
        mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=0.5)
    except Exception as e:
        logger.warning(f"React surprised error: {e}")


def react_neutral(mini):
    """Gentle return to neutral — calm acknowledgment."""
    try:
        mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=0.6)
    except Exception as e:
        logger.warning(f"React neutral error: {e}")


def react_thinking(mini):
    """Head tilts to one side — classic thinking look."""
    try:
        side = random.choice([-14, 14])
        mini.goto_target(head=create_head_pose(roll=side, degrees=True), duration=0.6)
    except Exception as e:
        logger.warning(f"React thinking error: {e}")


# ── Idle Animations ────────────────────────────────────────────────────────────

def idle_loop(mini, stop_event: threading.Event):
    """
    Runs in a background thread while waiting for user input.
    Subtle, randomized movements to make Reachy feel alive.
    """
    idle_moves = [
        # Gentle head tilt left
        lambda: mini.goto_target(
            head=create_head_pose(roll=-8, degrees=True), duration=1.5
        ),
        # Gentle head tilt right
        lambda: mini.goto_target(
            head=create_head_pose(roll=8, degrees=True), duration=1.5
        ),
        # Subtle look up
        lambda: mini.goto_target(
            head=create_head_pose(z=5, mm=True), duration=1.5
        ),
        # Return to neutral
        lambda: mini.goto_target(
            head=create_head_pose(), antennas=[0, 0], duration=1.0
        ),
        # Gentle antenna bob
        lambda: (
            mini.goto_target(antennas=[0.15, 0.15], duration=0.8),
            mini.goto_target(antennas=[0, 0], duration=0.8),
        ),
        # Look left and back
        lambda: (
            mini.goto_target(head=create_head_pose(roll=-10, degrees=True), duration=1.2),
            mini.goto_target(head=create_head_pose(), duration=1.0),
        ),
        # Look right and back
        lambda: (
            mini.goto_target(head=create_head_pose(roll=10, degrees=True), duration=1.2),
            mini.goto_target(head=create_head_pose(), duration=1.0),
        ),
    ]

    while not stop_event.is_set():
        try:
            move = random.choice(idle_moves)
            result = move()
            stop_event.wait(timeout=random.uniform(3.0, 6.0))
        except Exception:
            break


# ── Convenience Functions ──────────────────────────────────────────────────────

def do_thinking_pose(mini, is_question: bool):
    """
    Trigger an appropriate thinking pose based on whether
    the user asked a question or made a statement.
    Silently ignores errors to avoid crashing the conversation.
    """
    try:
        poses = THINKING_QUESTION_POSES if is_question else THINKING_STATEMENT_POSES
        random.choice(poses)(mini)
    except Exception as e:
        logger.warning(f"Thinking pose error: {e}")


def do_listening_pose(mini):
    """Trigger an attentive listening pose."""
    try:
        random.choice(LISTENING_POSES)(mini)
    except Exception as e:
        logger.warning(f"Listening pose error: {e}")


def do_mood_reaction(mini, mood: str):
    """Trigger a mood-appropriate robot reaction."""
    try:
        if mood == "happy":
            react_happy(mini)
        elif mood == "surprised":
            react_surprised(mini)
        elif mood == "thinking":
            react_thinking(mini)
        else:
            react_neutral(mini)
    except Exception as e:
        logger.warning(f"Mood reaction error: {e}")


def return_to_neutral(mini):
    """Smoothly return to default resting pose."""
    try:
        mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=0.7)
    except Exception as e:
        logger.warning(f"Return to neutral error: {e}")