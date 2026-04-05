"""
reachy_chat.py
Main entry point for the Reachy Mini CPS Facilitator.

Architecture:
- LLM: Claude API (primary) with Ollama fallback
- STT: faster-whisper (local)
- TTS: edge-tts (Microsoft Neural TTS)
- Robot: reachy-mini SDK (sim or real hardware)
- CPS: stage-aware facilitation via cps_manager
- Memory: rolling 5-session memory via memory_manager
- Dashboard: live state updates via dashboard_state

Recording:
- Press Enter once to START speaking
- Press Enter again to STOP speaking and trigger response

Additions:
- Mic check on startup
- Idle animations while waiting for input
- Stage-specific greetings on transition
- Session summary on quit
"""

import asyncio
import logging
import os
import random
import threading
import time
import uuid

import anthropic
import edge_tts
import numpy as np
import ollama
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

from cps_manager import (
    STAGES, build_system_prompt, check_for_advance,
    next_stage, stage_label
)
from memory_manager import (
    append_to_session, build_history_context,
    close_session, load_memory, start_session,
    save_stage, load_stage_state, export_session,
    load_session_id, save_session_id, new_session_id,
    MEMORY_FILE, STAGE_FILE, SESSION_FILE
)
import dashboard_state as ds

# ── Logging Setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("reachy.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

for noisy in ["reachy_mini", "httpx", "faster_whisper", "root"]:
    logging.getLogger(noisy).setLevel(logging.ERROR)


# ── Configuration ─────────────────────────────────────────────────────────────

OLLAMA_MODEL     = "llama3.2:3b"
CLAUDE_MODEL     = "claude-haiku-4-5-20251001"
SAMPLE_RATE      = 16000
VOICE            = "en-US-AriaNeural"
MIN_AUDIO_VOLUME = 0.0005

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
USE_CLAUDE        = bool(ANTHROPIC_API_KEY)
LAUNCHER_MODE     = os.environ.get("REACHY_SESSION_MODE")

THINKING_PHRASES = [
    "Hmm, let me think about that...",
    "Good question, give me a moment...",
    "Let me sit with that for a second...",
    "Interesting, let me think...",
    "Mmm, give me just a moment...",
    "Let me reflect on that...",
]

# Stage-specific greetings when transitioning into a new stage
STAGE_GREETINGS = {
    "clarify": [
        "Let's start by really understanding your challenge. Tell me what's on your mind.",
        "I'm ready to explore this with you. What's the challenge you're working on?",
        "Let's dig into this together. What would it be great if you could achieve?",
    ],
    "ideate": [
        "Alright — brainstorming time! No idea is too wild here. Let's go!",
        "Time to get creative. We're going for volume — as many ideas as possible!",
        "Let's open the floodgates. Every idea counts at this stage, even the crazy ones!",
    ],
    "develop": [
        "Now we get to strengthen your best idea. Let's make it as solid as possible.",
        "Time to dig deeper. Let's figure out what's great about this idea and what needs work.",
        "Let's build this out properly — the good, the exciting, and the challenges.",
    ],
    "implement": [
        "Time to make it real. Let's turn this plan into concrete next steps.",
        "We're in the home stretch — let's figure out exactly how to make this happen.",
        "Let's get specific. What does actually doing this look like?",
    ],
}

BASE_SYSTEM_PROMPT = """You are Reachy Mini, a friendly, curious, and expressive small robot companion
and Creative Problem Solving facilitator. You speak in short, warm, conversational sentences.
Keep responses to 1-3 sentences unless you need more to facilitate effectively.
You have memory of past conversations and may reference them naturally when relevant.

When you feel the current CPS stage is complete and the user has answered the key questions
for that stage, end your response by naturally asking if they are ready to move on to the
next stage. For example: "I think we've got a really clear picture here — want to move into
brainstorming ideas?" or "That feels like a solid plan — ready to move on to the next stage?"
Do NOT automatically advance — always ask first and let the user decide.

When your response contains a key artifact, tag it on a new line using one of these formats:
ARTIFACT_CHALLENGE: <the challenge statement>
ARTIFACT_FOCUS: <the focus question>
ARTIFACT_IDEA: <a single idea>
ARTIFACT_CLUSTER: <a cluster heading>
ARTIFACT_PLUS: <a plus/strength>
ARTIFACT_POTENTIAL: <a potential>
ARTIFACT_CONCERN: <a concern>
ARTIFACT_ACTION: <an action step>
ARTIFACT_COMMIT: <a committed action>
Only tag artifacts when they are clearly and explicitly stated. Do not force tags.

After your response, on a new line write:
MOOD: [one of: happy, thinking, surprised, neutral]"""


# ── Whisper Model ─────────────────────────────────────────────────────────────

try:
    WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
    logger.info("Whisper model loaded successfully.")
except Exception as e:
    logger.critical(f"Failed to load Whisper model: {e}")
    raise


# ── TTS ───────────────────────────────────────────────────────────────────────

async def _speak_async(text: str, filepath: str):
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(filepath)


def speak(text: str):
    filepath = f"tts_{uuid.uuid4().hex[:8]}.wav"
    try:
        asyncio.run(_speak_async(text, filepath))
        data, samplerate = sf.read(filepath)
        sd.play(data, samplerate)
        sd.wait()
    except Exception as e:
        logger.error(f"TTS/audio playback error: {e}")
        print(f"[Reachy would say]: {text}")
    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass


# ── Mic Check ─────────────────────────────────────────────────────────────────

def check_mic() -> bool:
    """
    Record 1 second of audio and check the volume level.
    Returns True if mic is working, False if too quiet.
    Warns the user but does not block startup.
    """
    print("🎤 Checking microphone...")
    try:
        audio = sd.rec(int(SAMPLE_RATE * 1.0), samplerate=SAMPLE_RATE,
                       channels=1, dtype="float32")
        sd.wait()
        volume = np.sqrt(np.mean(audio**2))
        if volume < MIN_AUDIO_VOLUME:
            print("⚠️  Mic seems very quiet. Check your microphone settings before speaking.")
            logger.warning(f"Mic check failed — volume: {volume:.4f}")
            return False
        else:
            print(f"✅ Mic OK (volume: {volume:.4f})")
            logger.info(f"Mic check passed — volume: {volume:.4f}")
            return True
    except Exception as e:
        logger.error(f"Mic check error: {e}")
        print("⚠️  Could not check microphone. Proceeding anyway.")
        return False


# ── Robot Expressions ─────────────────────────────────────────────────────────

def express_mood(mini, mood: str):
    try:
        if mood == "happy":
            mini.goto_target(antennas=[0.6, 0.6], duration=0.3)
            mini.goto_target(antennas=[0, 0], duration=0.3)
        elif mood == "thinking":
            mini.goto_target(head=create_head_pose(roll=15, degrees=True), duration=0.5)
        elif mood == "surprised":
            mini.goto_target(head=create_head_pose(z=15, mm=True), duration=0.3)
            mini.goto_target(antennas=[0.8, 0.8], duration=0.2)
            mini.goto_target(antennas=[0, 0], duration=0.3)
        else:
            mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=0.5)
    except Exception as e:
        logger.warning(f"Robot expression error (mood={mood}): {e}")


# ── Idle Animations ───────────────────────────────────────────────────────────

_idle_stop  = threading.Event()
_idle_thread = None


def _idle_loop(mini):
    """
    Runs in a background thread while waiting for user input.
    Performs subtle, randomized idle movements to make Reachy feel alive.
    """
    idle_moves = [
        # Gentle head tilt left
        lambda: mini.goto_target(head=create_head_pose(roll=-8, degrees=True), duration=1.5),
        # Gentle head tilt right
        lambda: mini.goto_target(head=create_head_pose(roll=8, degrees=True), duration=1.5),
        # Subtle look up
        lambda: mini.goto_target(head=create_head_pose(z=5, mm=True), duration=1.5),
        # Return to neutral
        lambda: mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=1.0),
        # Gentle antenna bob
        lambda: (
            mini.goto_target(antennas=[0.15, 0.15], duration=0.8),
            mini.goto_target(antennas=[0, 0], duration=0.8)
        ),
    ]

    while not _idle_stop.is_set():
        try:
            move = random.choice(idle_moves)
            move()
            # Wait 3-6 seconds between idle moves
            _idle_stop.wait(timeout=random.uniform(3.0, 6.0))
        except Exception:
            break


def start_idle(mini):
    """Start idle animation in background thread."""
    global _idle_thread, _idle_stop
    _idle_stop.clear()
    _idle_thread = threading.Thread(target=_idle_loop, args=(mini,), daemon=True)
    _idle_thread.start()


def stop_idle():
    """Stop idle animation and wait for thread to finish."""
    global _idle_thread
    _idle_stop.set()
    if _idle_thread and _idle_thread.is_alive():
        _idle_thread.join(timeout=2.0)
    _idle_thread = None


# ── Response Parsing + Artifact Extraction ────────────────────────────────────

ARTIFACT_TAGS = {
    "ARTIFACT_CHALLENGE": ("clarify",   "challenge_statement", "set"),
    "ARTIFACT_FOCUS":     ("clarify",   "focus_question",      "set"),
    "ARTIFACT_IDEA":      ("ideate",    "ideas",               "append"),
    "ARTIFACT_CLUSTER":   ("ideate",    "clusters",            "append"),
    "ARTIFACT_PLUS":      ("develop",   "plusses",             "append"),
    "ARTIFACT_POTENTIAL": ("develop",   "potentials",          "append"),
    "ARTIFACT_CONCERN":   ("develop",   "concerns",            "append"),
    "ARTIFACT_ACTION":    ("develop",   "action_steps",        "append"),
    "ARTIFACT_COMMIT":    ("implement", "committed_actions",   "append"),
}


def parse_response(raw: str) -> tuple[str, str]:
    lines      = raw.strip().split("\n")
    mood       = "neutral"
    text_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("MOOD:"):
            mood = stripped.replace("MOOD:", "").strip().lower()
            continue
        matched = False
        for tag, (stage, key, action) in ARTIFACT_TAGS.items():
            if stripped.startswith(f"{tag}:"):
                value = stripped[len(tag) + 1:].strip()
                if value:
                    if action == "set":
                        ds.set_artifact(stage, key, value)
                    else:
                        ds.append_artifact(stage, key, value)
                    logger.info(f"Artifact captured [{tag}]: {value}")
                matched = True
                break
        if not matched:
            text_lines.append(line)

    return " ".join(text_lines).strip(), mood


# ── LLM ──────────────────────────────────────────────────────────────────────

def llm_call(system_prompt: str, messages: list) -> str:
    if USE_CLAUDE:
        try:
            client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )
            logger.info("LLM response received from Claude API.")
            return response.content[0].text
        except anthropic.APIConnectionError:
            logger.warning("Claude API connection failed — falling back to Ollama.")
        except anthropic.RateLimitError:
            logger.warning("Claude API rate limit hit — falling back to Ollama.")
        except Exception as e:
            logger.warning(f"Claude API error: {e} — falling back to Ollama.")

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "system", "content": system_prompt}] + messages,
        )
        logger.info("LLM response received from Ollama.")
        return response["message"]["content"]
    except Exception as e:
        logger.error(f"Ollama fallback also failed: {e}")
        raise RuntimeError("Both Claude API and Ollama failed to respond.") from e


# ── Audio Input ───────────────────────────────────────────────────────────────

def record_audio() -> str:
    time.sleep(0.5)  # brief pause to let TTS audio tail off
    print("🎤 Recording... press Enter again when you're done speaking.")

    chunks    = []
    stop_flag = threading.Event()
    filepath  = f"input_{uuid.uuid4().hex[:8]}.wav"

    def record():
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32", blocksize=1024) as stream:
                while not stop_flag.is_set():
                    chunk, _ = stream.read(1024)
                    chunks.append(chunk.copy())
        except Exception as e:
            logger.error(f"Recording stream error: {e}")

    thread = threading.Thread(target=record, daemon=True)
    thread.start()

    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass

    stop_flag.set()
    thread.join(timeout=2.0)

    if not chunks:
        print("Nothing recorded — please try again.")
        return ""

    audio  = np.concatenate(chunks, axis=0)
    volume = np.sqrt(np.mean(audio**2))

    if volume < MIN_AUDIO_VOLUME:
        print("Too quiet — please speak up and try again.")
        return ""

    try:
        sf.write(filepath, audio, SAMPLE_RATE)
        segments, _ = WHISPER_MODEL.transcribe(filepath)
        text = " ".join(s.text for s in segments).strip()
        logger.info(f"Transcribed: {text}")
        print(f"You: {text}")
        return text
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        print("Transcription failed — please try again.")
        return ""
    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass


# ── Main Chat Turn ────────────────────────────────────────────────────────────

def chat(mini, current_session: dict, past_context: list,
         user_message: str, current_stage: str) -> None:
    system_prompt = build_system_prompt(current_stage, BASE_SYSTEM_PROMPT)
    append_to_session(current_session, "user", user_message)
    ds.add_transcript_entry("user", user_message, current_stage)
    messages = past_context + current_session["history"]

    stop_idle()
    express_mood(mini, "thinking")
    speak(random.choice(THINKING_PHRASES))

    try:
        raw = llm_call(system_prompt, messages)
    except RuntimeError as e:
        logger.error(str(e))
        speak("I'm having trouble thinking right now — could you give me a moment and try again?")
        start_idle(mini)
        return

    text, mood = parse_response(raw)
    logger.info(f"Stage={stage_label(current_stage)} Mood={mood}")
    print(f"Reachy ({mood}) [{stage_label(current_stage)}]: {text}")

    ds.add_transcript_entry("assistant", text, current_stage)
    express_mood(mini, mood)
    speak(text)
    append_to_session(current_session, "assistant", text)

    # Resume idle after speaking
    start_idle(mini)


# ── Session Summary ───────────────────────────────────────────────────────────

def generate_summary(current_session: dict, current_stage: str) -> str:
    """
    Generate a brief spoken summary of what was accomplished this session.
    Uses the session history to count exchanges and note the stage reached.
    """
    history  = current_session.get("history", [])
    exchanges = len([m for m in history if m["role"] == "user"])

    if exchanges == 0:
        return "We didn't get much done this time — but I'll be here when you're ready!"

    stage = stage_label(current_stage)

    if exchanges <= 3:
        return f"Short session today — we made a start in the {stage} stage. See you next time!"
    elif exchanges <= 8:
        return f"Good work today! We had {exchanges} exchanges in the {stage} stage. Making solid progress."
    else:
        return f"That was a productive session — {exchanges} exchanges and we're well into the {stage} stage. Great work!"


# ── Session Mode ──────────────────────────────────────────────────────────────

def prompt_session_mode() -> bool:
    if LAUNCHER_MODE == "new":
        return True
    if LAUNCHER_MODE == "continue":
        return False

    has_previous = any(
        os.path.exists(f) for f in [MEMORY_FILE, STAGE_FILE, SESSION_FILE]
    )
    if not has_previous:
        return True

    print("\nA previous session was found.")
    print("  [1] Continue previous session")
    print("  [2] Start fresh\n")

    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            return False
        elif choice == "2":
            return True
        else:
            print("Please enter 1 or 2.")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    logger.info("Reachy Mini CPS Facilitator starting up.")
    print("\n=== Reachy Mini CPS Facilitator ===")

    if USE_CLAUDE:
        print("LLM: Claude API (claude-haiku)")
    else:
        print("LLM: Ollama fallback (no ANTHROPIC_API_KEY found)")
        logger.warning("ANTHROPIC_API_KEY not set — using Ollama. Expect slower responses.")

    # Mic check
    check_mic()

    start_fresh = prompt_session_mode()

    if start_fresh:
        for f in [MEMORY_FILE, STAGE_FILE, SESSION_FILE]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except IOError as e:
                    logger.error(f"Could not clear {f}: {e}")
        session_id = new_session_id()
        save_session_id(session_id)
        ds.reset()
    else:
        session_id = load_session_id()
        if not session_id:
            session_id = new_session_id()
            save_session_id(session_id)

    sessions        = load_memory()
    past_context    = build_history_context(sessions)
    current_session = start_session()
    current_stage   = load_stage_state() or STAGES[0]

    ds.set_stage(current_stage)
    ds.set_active(True)

    print(f"\nCPS Stage: {stage_label(current_stage)}")
    print(f"Memory: {len(sessions)} past session(s) loaded")
    print("=" * 35)
    print("\nHow to speak:")
    print("  1. Press Enter to START recording")
    print("  2. Speak your message")
    print("  3. Press Enter again to STOP and send")
    print("  Type 'quit' to exit.\n")

    try:
        with ReachyMini() as mini:
            logger.info("Connected to Reachy Mini.")

            # Opening greeting
            speak("Hey there! I'm here whenever you're ready to talk. What's on your mind?")
            start_idle(mini)

            while True:
                try:
                    cmd = input("\nPress Enter to speak (or type 'quit'): ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    break

                if cmd == "quit":
                    stop_idle()
                    summary = generate_summary(current_session, current_stage)
                    speak(summary)
                    speak("See you next time!")
                    break

                stop_idle()
                user_input = record_audio()
                if not user_input:
                    start_idle(mini)
                    continue

                if check_for_advance(user_input):
                    nxt = next_stage(current_stage)
                    if nxt:
                        current_stage = nxt
                        save_stage(current_stage)
                        ds.set_stage(current_stage)
                        logger.info(f"Advancing to stage: {current_stage}")
                        print(f"\n--- Stage: {stage_label(current_stage)} ---\n")
                        # Stage-specific greeting
                        greeting = random.choice(STAGE_GREETINGS[current_stage])
                        speak(greeting)
                    else:
                        logger.info("All CPS stages complete.")
                        print("\n--- All stages complete! ---\n")
                        speak("We've made it through the whole process — amazing work!")
                    start_idle(mini)
                    continue

                chat(mini, current_session, past_context, user_input, current_stage)

    except ConnectionError as e:
        logger.critical(f"Could not connect to Reachy Mini: {e}")
        print("\nCould not connect to Reachy Mini. Make sure the daemon is running.")
    except Exception as e:
        logger.critical(f"Unexpected error: {e}", exc_info=True)
        print(f"\nUnexpected error: {e}")
    finally:
        stop_idle()
        ds.set_active(False)
        close_session(sessions, current_session)
        export_session(current_session, session_id)
        save_stage(current_stage)
        logger.info("Session saved. Shutting down.")
        print("\nSession saved. Goodbye!")


if __name__ == "__main__":
    main()