"""
reachy_chat.py
Main entry point for the Reachy Mini CPS Facilitator.

Architecture:
- LLM: Claude API (primary) with Ollama fallback
- STT: faster-whisper (local)
- TTS: edge-tts (Microsoft Neural TTS) via pygame MP3 playback
- Robot: reachy-mini SDK (sim or real hardware)
- CPS: stage-aware facilitation via cps_manager
- Memory: rolling 5-session memory via memory_manager
- Dashboard: live state updates via dashboard_state

Recording:
- Press Enter once to START speaking
- Press Enter again to STOP speaking and trigger response

Fixes applied:
- Artifact tags stripped from spoken text (never spoken aloud)
- Empty LLM response fallback phrases
- Markdown cleaned before TTS (no asterisks spoken)
- Numbered list with natural pauses instead of bullet run-ons
- pygame MP3 playback for cross-platform TTS compatibility
- Context-aware thinking phrases (question vs statement)
- Consent check on startup — Reachy asks if user is ready before CPS begins
"""

import asyncio
import logging
import os
import random
import re
import threading
import time
import uuid

from dotenv import load_dotenv
load_dotenv()

import anthropic
import edge_tts
import numpy as np
import ollama
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
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
from behaviors import (
    do_thinking_pose, do_listening_pose, do_mood_reaction,
    talking_animation, idle_loop, return_to_neutral
)

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

THINKING_PHRASES_QUESTION = [
    "Good question, give me a moment...",
    "Hmm, let me think about that...",
    "Interesting question, let me reflect...",
    "Let me sit with that for a second...",
    "That's worth thinking about carefully...",
]

THINKING_PHRASES_STATEMENT = [
    "Let me reflect on that...",
    "Mmm, give me just a moment...",
    "I hear you, let me think...",
    "Got it, just a moment...",
    "Let me process that...",
]

EMPTY_RESPONSE_FALLBACKS = [
    "I hear you — tell me more.",
    "Got it. What else can you share?",
    "Understood. Keep going.",
    "That makes sense. What else is on your mind?",
    "I'm with you. What else?",
]

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

# Phrases that count as "yes" for the consent check
CONSENT_YES = [
    "yes", "yeah", "yep", "yup", "sure", "ready", "let's go", "lets go",
    "absolutely", "definitely", "of course", "go ahead", "start", "begin",
    "i'm ready", "im ready", "let's begin", "lets begin",
]

# Phrases that count as "no" for the consent check
CONSENT_NO = [
    "no", "nope", "not yet", "not now", "wait", "later", "hold on",
    "give me a minute", "give me a second", "not ready",
]

BASE_SYSTEM_PROMPT = """You are Reachy Mini, a friendly, curious, and expressive small robot companion
and Creative Problem Solving facilitator. You speak in short, warm, conversational sentences.
Keep responses to 1-3 sentences unless you need more to facilitate effectively.
You have memory of past conversations and may reference them naturally when relevant.

When you feel the current CPS stage is complete, do the following in order:
1. Speak a brief summary of what was covered in this stage — what the user shared, what was clarified, what was decided.
2. Tell the user which stage comes next and what it involves.
3. Say exactly this: "Whenever you're ready, just say 'I'm ready to move on to the next stage' and we'll continue."
Do NOT advance automatically. Do NOT move on until the user says that phrase or something very close to it.

IMPORTANT: You are the facilitator — YOU lead the process. Never ask the user what the next
step should be. Always guide them forward confidently.

When your response contains a key artifact, tag it on a new line using one of these formats.
These tags are NEVER spoken aloud — they are metadata only:
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
Do NOT mention the artifact tags in your spoken response — they are silent metadata.

After your response, on a new line write:
MOOD: [one of: happy, thinking, surprised, neutral]"""


# ── Whisper Model ─────────────────────────────────────────────────────────────

try:
    WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
    logger.info("Whisper model loaded successfully.")
except Exception as e:
    logger.critical(f"Failed to load Whisper model: {e}")
    raise


# ── Text Cleaning for Speech ──────────────────────────────────────────────────

def clean_for_speech(text: str) -> str:
    text = re.sub(r'ARTIFACT_\w+:.*', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)

    lines   = text.split('\n')
    cleaned = []
    counter = 1

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('* ') or stripped.startswith('- '):
            content = stripped[2:].strip()
            cleaned.append(f"{counter}. {content}")
            counter += 1
        else:
            if cleaned and not cleaned[-1].endswith('.'):
                cleaned[-1] += '.'
            cleaned.append(stripped)
            counter = 1

    result = ' '.join(cleaned)
    result = re.sub(r'\.\.+', '.', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


# ── TTS ───────────────────────────────────────────────────────────────────────

async def _speak_async(text: str, filepath: str):
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(filepath)


def speak(text: str):
    if not text or not text.strip():
        logger.warning("speak() called with empty text — skipping.")
        return

    filepath = f"tts_{uuid.uuid4().hex[:8]}.mp3"
    try:
        asyncio.run(_speak_async(text, filepath))

        if not os.path.exists(filepath) or os.path.getsize(filepath) < 500:
            logger.warning("TTS file too small or missing — skipping playback.")
            print(f"[Reachy would say]: {text}")
            return

        pygame.mixer.init()
        pygame.mixer.music.load(filepath)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)
        pygame.mixer.music.stop()
        pygame.mixer.quit()

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
    print("🎤 Checking microphone...")
    try:
        audio  = sd.rec(int(SAMPLE_RATE * 1.0), samplerate=SAMPLE_RATE,
                        channels=1, dtype="float32")
        sd.wait()
        volume = np.sqrt(np.mean(audio**2))
        if volume < MIN_AUDIO_VOLUME:
            print("⚠️  Mic seems very quiet. Check your microphone settings before speaking.")
            logger.warning(f"Mic check failed — volume: {volume:.4f}")
            return False
        print(f"✅ Mic OK (volume: {volume:.4f})")
        logger.info(f"Mic check passed — volume: {volume:.4f}")
        return True
    except Exception as e:
        logger.error(f"Mic check error: {e}")
        print("⚠️  Could not check microphone. Proceeding anyway.")
        return False


# ── Robot Expressions ─────────────────────────────────────────────────────────

# Robot expressions handled by behaviors.py


# ── Idle Animations ───────────────────────────────────────────────────────────

_idle_stop   = threading.Event()
_idle_thread = None


def start_idle(mini):
    global _idle_thread, _idle_stop
    _idle_stop.clear()
    _idle_thread = threading.Thread(target=idle_loop, args=(mini, _idle_stop), daemon=True)
    _idle_thread.start()


def stop_idle():
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

    text = " ".join(text_lines).strip()
    return text, mood


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
    time.sleep(0.5)
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


# ── Consent Check ─────────────────────────────────────────────────────────────

def consent_check(mini) -> bool:
    """
    Wait for user to press Enter, ask if they're ready to begin CPS.
    Returns True if yes, False if no.
    Loops back if the response is unclear.
    """
    while True:
        try:
            input("\nPress Enter to begin the CPS process with Reachy Mini: ")
        except (EOFError, KeyboardInterrupt):
            return False

        speak("Hey! Are you ready to begin the Creative Problem Solving process?")

        do_listening_pose(mini)
        user_input = record_audio()

        if not user_input:
            speak("I didn't catch that — just say yes or no.")
            continue

        lowered = user_input.lower().strip()

        if any(w in lowered for w in CONSENT_YES):
            logger.info("Consent check: user said yes.")
            return True
        elif any(w in lowered for w in CONSENT_NO):
            logger.info("Consent check: user said no.")
            speak("No problem — I'll be right here whenever you're ready.")
            return False
        else:
            speak("I didn't quite catch that — just say yes if you're ready, or no if you'd like to wait.")


# ── Session Summary ───────────────────────────────────────────────────────────

def generate_summary(current_session: dict, current_stage: str) -> str:
    history   = current_session.get("history", [])
    exchanges = len([m for m in history if m["role"] == "user"])
    stage     = stage_label(current_stage)

    if exchanges == 0:
        return "We didn't get much done this time — but I'll be here when you're ready!"
    elif exchanges <= 3:
        return f"Short session today — we made a start in the {stage} stage. See you next time!"
    elif exchanges <= 8:
        return f"Good work today! We had {exchanges} exchanges in the {stage} stage. Making solid progress."
    else:
        return f"That was a productive session — {exchanges} exchanges and we're well into the {stage} stage. Great work!"


# ── Main Chat Turn ────────────────────────────────────────────────────────────

def chat(mini, current_session: dict, past_context: list,
         user_message: str, current_stage: str) -> None:
    system_prompt = build_system_prompt(current_stage, BASE_SYSTEM_PROMPT)
    append_to_session(current_session, "user", user_message)
    ds.add_transcript_entry("user", user_message, current_stage)
    messages = past_context + current_session["history"]

    stop_idle()

    is_question = user_message.strip().endswith("?")
    do_thinking_pose(mini, is_question)
    phrases = THINKING_PHRASES_QUESTION if is_question else THINKING_PHRASES_STATEMENT
    speak(random.choice(phrases))

    try:
        raw = llm_call(system_prompt, messages)
    except RuntimeError as e:
        logger.error(str(e))
        speak("I'm having trouble thinking right now — could you give me a moment and try again?")
        start_idle(mini)
        return

    text, mood = parse_response(raw)

    if not text.strip():
        text = random.choice(EMPTY_RESPONSE_FALLBACKS)
        logger.warning("LLM returned empty text — using fallback phrase.")

    text = clean_for_speech(text)

    logger.info(f"Stage={stage_label(current_stage)} Mood={mood}")
    print(f"Reachy ({mood}) [{stage_label(current_stage)}]: {text}")

    ds.add_transcript_entry("assistant", text, current_stage)

    do_mood_reaction(mini, mood)

    talk_stop   = threading.Event()
    talk_thread = threading.Thread(
        target=talking_animation, args=(mini, talk_stop), daemon=True
    )
    talk_thread.start()
    speak(text)
    talk_stop.set()
    talk_thread.join(timeout=2.0)
    return_to_neutral(mini)

    append_to_session(current_session, "assistant", text)
    start_idle(mini)


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
            start_idle(mini)

            # ── Consent check loop ────────────────────────────────────────────
            # Keep looping until user says yes or exits
            while True:
                ready = consent_check(mini)
                if ready:
                    speak(random.choice(STAGE_GREETINGS[current_stage]))
                    break
                # If no — loop back to "Press Enter to begin"

            # ── Main conversation loop ────────────────────────────────────────
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
                do_listening_pose(mini)
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