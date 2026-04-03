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

Recording:
- Press Enter once to START speaking
- Press Enter again to STOP speaking and trigger response
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
    save_stage, load_stage_state, export_session
)

# ── Logging Setup ─────────────────────────────────────────────────────────────
# Suppress noisy third-party loggers so the terminal stays readable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("reachy.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Suppress noisy reachy_mini and httpx logs from terminal (still go to file)
for noisy in ["reachy_mini", "httpx", "faster_whisper", "root"]:
    logging.getLogger(noisy).setLevel(logging.ERROR)
    for handler in logging.getLogger(noisy).handlers:
        handler.setLevel(logging.ERROR)


# ── Configuration ─────────────────────────────────────────────────────────────

OLLAMA_MODEL     = "llama3.2:3b"
CLAUDE_MODEL     = "claude-haiku-4-5-20251001"
SAMPLE_RATE      = 16000
VOICE            = "en-US-AriaNeural"
MIN_AUDIO_VOLUME = 0.0005  # Lowered slightly for normal mic distance

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
USE_CLAUDE        = bool(ANTHROPIC_API_KEY)

THINKING_PHRASES = [
    "Hmm, let me think about that...",
    "Good question, give me a moment...",
    "Let me sit with that for a second...",
    "Interesting, let me think...",
    "Mmm, give me just a moment...",
    "Let me reflect on that...",
]

BASE_SYSTEM_PROMPT = """You are Reachy Mini, a friendly, curious, and expressive small robot companion
and Creative Problem Solving facilitator. You speak in short, warm, conversational sentences.
Keep responses to 1-3 sentences unless you need more to facilitate effectively.
You have memory of past conversations and may reference them naturally when relevant.

When you feel the current CPS stage is complete and the user has answered the key questions
for that stage, end your response by naturally asking if they are ready to move on to the
next stage. For example: "I think we've got a really clear picture here — want to move into
brainstorming ideas?" or "That feels like a solid plan — ready to move on to the next stage?"
Do NOT automatically advance — always ask first and let the user decide.

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
    """Generate TTS audio and save to a unique filepath."""
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(filepath)


def speak(text: str):
    """
    Convert text to speech and play it.
    Uses a unique filename per call to avoid file lock conflicts.
    Falls back to printing the text if audio playback fails.
    """
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
        # Clean up temp file
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass


# ── Robot Expressions ─────────────────────────────────────────────────────────

def express_mood(mini, mood: str):
    """
    Trigger robot movement based on detected mood.
    Silently skips on error to avoid crashing the conversation.
    """
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


# ── Response Parsing ──────────────────────────────────────────────────────────

def parse_response(raw: str) -> tuple[str, str]:
    """
    Parse the LLM response into (text, mood).
    Extracts MOOD: tag and returns clean spoken text.
    """
    lines  = raw.strip().split("\n")
    mood   = "neutral"
    text_lines = []

    for line in lines:
        if line.startswith("MOOD:"):
            mood = line.replace("MOOD:", "").strip().lower()
        else:
            text_lines.append(line)

    text = " ".join(text_lines).strip()
    return text, mood


# ── LLM ──────────────────────────────────────────────────────────────────────

def llm_call(system_prompt: str, messages: list) -> str:
    """
    Call the LLM. Uses Claude API if ANTHROPIC_API_KEY is set,
    otherwise falls back to Ollama. Raises on total failure.
    """
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

    # Ollama fallback
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
    """
    Record audio from the microphone using a background thread.
    - This function is called after the first Enter press in the main loop.
    - Press Enter again to stop recording and trigger transcription.
    Uses a unique filename to avoid file lock conflicts.
    """
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
        logger.warning("Audio too quiet — possible mic issue.")
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
    """
    Process one conversation turn:
    1. Acknowledge with a thinking phrase and expression
    2. Call the LLM
    3. Parse response
    4. Express mood and speak
    5. Save to session history
    """
    system_prompt = build_system_prompt(current_stage, BASE_SYSTEM_PROMPT)
    append_to_session(current_session, "user", user_message)
    messages = past_context + current_session["history"]

    # Acknowledge while LLM generates
    express_mood(mini, "thinking")
    speak(random.choice(THINKING_PHRASES))

    try:
        raw = llm_call(system_prompt, messages)
    except RuntimeError as e:
        logger.error(str(e))
        speak("I'm having trouble thinking right now — could you give me a moment and try again?")
        return

    text, mood = parse_response(raw)
    logger.info(f"Stage={stage_label(current_stage)} Mood={mood}")
    print(f"Reachy ({mood}) [{stage_label(current_stage)}]: {text}")

    express_mood(mini, mood)
    speak(text)
    append_to_session(current_session, "assistant", text)


# ── Session Mode Prompt ───────────────────────────────────────────────────────

def prompt_session_mode() -> bool:
    """
    Ask the user at startup whether to continue the previous session
    or start fresh. Returns True if starting fresh.
    """
    from memory_manager import MEMORY_FILE, STAGE_FILE
    has_memory = os.path.exists(MEMORY_FILE) or os.path.exists(STAGE_FILE)

    if not has_memory:
        return True  # Nothing to continue, always start fresh

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
        logger.info("Using Claude API for LLM responses.")
    else:
        print("LLM: Ollama fallback (no ANTHROPIC_API_KEY found)")
        logger.warning("ANTHROPIC_API_KEY not set — using Ollama. Expect slower responses.")

    # Ask user whether to continue or start fresh
    start_fresh = prompt_session_mode()

    if start_fresh:
        # Clear saved state
        for f in ["memory.json", "stage_state.json"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                    logger.info(f"Cleared: {f}")
                except IOError as e:
                    logger.error(f"Could not clear {f}: {e}")

    # Load memory and stage
    sessions        = load_memory()
    past_context    = build_history_context(sessions)
    current_session = start_session()
    current_stage   = load_stage_state() or STAGES[0]

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
            speak("Hey there! I'm here whenever you're ready to talk. What's on your mind?")

            while True:
                try:
                    cmd = input("\nPress Enter to speak (or type 'quit'): ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    break

                if cmd == "quit":
                    speak("It was great thinking with you. See you next time!")
                    break

                user_input = record_audio()
                if not user_input:
                    continue

                # Check if user explicitly wants to advance stage
                if check_for_advance(user_input):
                    nxt = next_stage(current_stage)
                    if nxt:
                        current_stage = nxt
                        save_stage(current_stage)
                        logger.info(f"Advancing to stage: {current_stage}")
                        print(f"\n--- Stage: {stage_label(current_stage)} ---\n")
                        speak(f"Great — let's move into the {stage_label(current_stage)} stage!")
                    else:
                        logger.info("All CPS stages complete.")
                        print("\n--- All stages complete! ---\n")
                        speak("We've made it through the whole process — amazing work!")
                    continue

                # Normal conversation turn
                chat(mini, current_session, past_context, user_input, current_stage)

    except ConnectionError as e:
        logger.critical(f"Could not connect to Reachy Mini: {e}")
        print("\nCould not connect to Reachy Mini. Make sure the daemon is running.")
    except Exception as e:
        logger.critical(f"Unexpected error: {e}", exc_info=True)
        print(f"\nUnexpected error: {e}")
    finally:
        close_session(sessions, current_session)
        export_session(current_session)
        save_stage(current_stage)
        logger.info("Session saved. Shutting down.")
        print("\nSession saved. Goodbye!")


if __name__ == "__main__":
    main()