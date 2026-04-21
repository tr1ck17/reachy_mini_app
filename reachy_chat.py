"""
reachy_chat.py
Main entry point for the Reachy Mini CPS Facilitator.

Fixes applied:
- Artifact tags stripped from spoken text (never spoken aloud)
- Empty LLM response fallback phrases
- Markdown cleaned before TTS (no asterisks spoken)
- Numbered list with natural pauses instead of bullet run-ons
- pygame MP3 playback for cross-platform TTS compatibility
- Context-aware thinking phrases (question vs statement)
- Reachy Mini Lite audio devices explicitly targeted (device indices)
- Sample rate set to 44100Hz to match Reachy Mini Audio hardware
- VAD continuous voice detection with wake phrase activation
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
    STAGES, build_system_prompt, check_for_advance, check_for_end,
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

# VAD — import if available, fall back to Enter-to-speak if not
try:
    from vad import VADListener, CONSENT_YES, WAKE_PHRASES
    USE_VAD = True
except ImportError:
    USE_VAD = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("reachy.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

for noisy in ["reachy_mini", "httpx", "faster_whisper", "root"]:
    logging.getLogger(noisy).setLevel(logging.ERROR)

# Configuration
OLLAMA_MODEL = "llama3.2:3b"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
VOICE        = "en-US-GuyNeural"

# Audio device indices for Reachy Mini Lite USB
# Run: uv run python -c "import sounddevice as sd; print(sd.query_devices())"
# to find correct indices if these change after reconnecting
SAMPLE_RATE          = 44100   # mic native sample rate for recording
MIN_AUDIO_VOLUME     = 0.0003
REACHY_INPUT_DEVICE  = 1      # Echo Cancelling Speakerphone (Reachy Mini Audio) - input
REACHY_OUTPUT_DEVICE = 12     # Echo Cancelling Speakerphone (Reachy Mini Audio) - output

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

BASE_SYSTEM_PROMPT = """You are Reachy Mini, a friendly, curious, and expressive small robot companion
and Creative Problem Solving facilitator. You speak in short, warm, conversational sentences.
Keep responses to 1-3 sentences unless you need more to facilitate effectively.
You have memory of past conversations and may reference them naturally when relevant.

When you feel the current CPS stage is complete, do the following in order:
1. Speak a brief summary of what was covered in this stage.
2. Tell the user which stage comes next and what it involves.
3. Say exactly this: "Whenever you're ready, just say 'I'm ready to move on to the next stage' and we'll continue."
Do NOT advance automatically. Do NOT move on until the user says that phrase.

IMPORTANT: You are the facilitator — YOU lead the process. Never ask the user what the next
step should be. Always guide them forward confidently.

When your response contains a key artifact, tag it on a new line. These tags are NEVER spoken:
ARTIFACT_CHALLENGE: <the challenge statement>
ARTIFACT_FOCUS: <the focus question>
ARTIFACT_IDEA: <a single idea>
ARTIFACT_CLUSTER: <a cluster heading>
ARTIFACT_PLUS: <a plus/strength>
ARTIFACT_POTENTIAL: <a potential>
ARTIFACT_CONCERN: <a concern>
ARTIFACT_ACTION: <an action step>
ARTIFACT_COMMIT: <a committed action>
Only tag artifacts when clearly and explicitly stated. Do not force tags.
Do NOT mention artifact tags in your spoken response — they are silent metadata.

After your response, on a new line write:
MOOD: [one of: happy, thinking, surprised, neutral]"""

try:
    WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
    logger.info("Whisper model loaded.")
except Exception as e:
    logger.critical(f"Failed to load Whisper: {e}")
    raise


def clean_for_speech(text: str) -> str:
    text = re.sub(r'ARTIFACT_\w+:.*', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    lines, cleaned, counter = text.split('\n'), [], 1
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('* ') or stripped.startswith('- '):
            cleaned.append(f"{counter}. {stripped[2:].strip()}")
            counter += 1
        else:
            if cleaned and not cleaned[-1].endswith('.'): cleaned[-1] += '.'
            cleaned.append(stripped)
            counter = 1
    result = ' '.join(cleaned)
    result = re.sub(r'\.\.+', '.', result)
    return re.sub(r'\s+', ' ', result).strip()


async def _speak_async(text: str, filepath: str):
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(filepath)


def speak(text: str):
    if not text or not text.strip():
        return
    filepath = f"tts_{uuid.uuid4().hex[:8]}.mp3"
    try:
        asyncio.run(_speak_async(text, filepath))
        if not os.path.exists(filepath) or os.path.getsize(filepath) < 500:
            print(f"[Reachy would say]: {text}")
            return
        pygame.mixer.init(devicename="Echo Cancelling Speakerphone (Reachy Mini Audio)")
        pygame.mixer.music.load(filepath)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)
        pygame.mixer.music.stop()
        pygame.mixer.quit()
    except Exception as e:
        logger.error(f"TTS error: {e}")
        print(f"[Reachy would say]: {text}")
    finally:
        try:
            if os.path.exists(filepath): os.remove(filepath)
        except Exception:
            pass


def check_mic() -> bool:
    print("Checking microphone...")
    try:
        audio = sd.rec(int(SAMPLE_RATE * 1.0), samplerate=SAMPLE_RATE,
                       channels=1, dtype="float32", device=REACHY_INPUT_DEVICE)
        sd.wait()
        volume = np.sqrt(np.mean(audio**2))
        if volume < MIN_AUDIO_VOLUME:
            print("Mic seems very quiet. Check your microphone settings.")
            logger.warning(f"Mic check failed — volume: {volume:.4f}")
            return False
        print(f"Mic OK (volume: {volume:.4f})")
        logger.info(f"Mic check passed — volume: {volume:.4f}")
        return True
    except Exception as e:
        logger.error(f"Mic check error: {e}")
        print("Could not check microphone. Proceeding anyway.")
        return False


_idle_stop = threading.Event()
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


def parse_response(raw: str) -> tuple:
    lines, mood, text_lines = raw.strip().split("\n"), "neutral", []
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
                    if action == "set": ds.set_artifact(stage, key, value)
                    else: ds.append_artifact(stage, key, value)
                    logger.info(f"Artifact [{tag}]: {value}")
                matched = True
                break
        if not matched:
            text_lines.append(line)
    return " ".join(text_lines).strip(), mood


def llm_call(system_prompt: str, messages: list) -> str:
    if USE_CLAUDE:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=CLAUDE_MODEL, max_tokens=1024,
                system=system_prompt, messages=messages,
            )
            logger.info("LLM response from Claude API.")
            return response.content[0].text
        except anthropic.APIConnectionError:
            logger.warning("Claude API connection failed — falling back to Ollama.")
        except anthropic.RateLimitError:
            logger.warning("Claude rate limit — falling back to Ollama.")
        except Exception as e:
            logger.warning(f"Claude error: {e} — falling back to Ollama.")
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "system", "content": system_prompt}] + messages,
        )
        logger.info("LLM response from Ollama.")
        return response["message"]["content"]
    except Exception as e:
        logger.error(f"Ollama failed: {e}")
        raise RuntimeError("Both Claude API and Ollama failed.") from e


def record_audio() -> str:
    time.sleep(0.5)
    print("Recording... press Enter again when you're done speaking.")
    chunks, stop_flag = [], threading.Event()
    filepath = f"input_{uuid.uuid4().hex[:8]}.wav"

    def record():
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32", blocksize=1024,
                                 device=REACHY_INPUT_DEVICE) as stream:
                while not stop_flag.is_set():
                    chunk, _ = stream.read(1024)
                    chunks.append(chunk.copy())
        except Exception as e:
            logger.error(f"Recording error: {e}")

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
    audio = np.concatenate(chunks, axis=0)
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
            if os.path.exists(filepath): os.remove(filepath)
        except Exception:
            pass


def generate_summary(current_session: dict, current_stage: str) -> str:
    history = current_session.get("history", [])
    exchanges = len([m for m in history if m["role"] == "user"])
    stage = stage_label(current_stage)
    if exchanges == 0:
        return "We didn't get much done this time — but I'll be here when you're ready!"
    elif exchanges <= 3:
        return f"Short session today — we made a start in the {stage} stage. See you next time!"
    elif exchanges <= 8:
        return f"Good work today! We had {exchanges} exchanges in the {stage} stage. Making solid progress."
    else:
        return f"That was a productive session — {exchanges} exchanges and we're well into the {stage} stage. Great work!"


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
        logger.warning("LLM returned empty text — using fallback.")
    text = clean_for_speech(text)
    logger.info(f"Stage={stage_label(current_stage)} Mood={mood}")
    print(f"Reachy ({mood}) [{stage_label(current_stage)}]: {text}")
    ds.add_transcript_entry("assistant", text, current_stage)
    do_mood_reaction(mini, mood)
    talk_stop = threading.Event()
    talk_thread = threading.Thread(target=talking_animation, args=(mini, talk_stop), daemon=True)
    talk_thread.start()
    speak(text)
    talk_stop.set()
    talk_thread.join(timeout=2.0)
    return_to_neutral(mini)
    append_to_session(current_session, "assistant", text)
    start_idle(mini)


def prompt_session_mode() -> bool:
    if LAUNCHER_MODE == "new": return True
    if LAUNCHER_MODE == "continue": return False
    has_previous = any(os.path.exists(f) for f in [MEMORY_FILE, STAGE_FILE, SESSION_FILE])
    if not has_previous: return True
    print("\nA previous session was found.")
    print("  [1] Continue previous session")
    print("  [2] Start fresh\n")
    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1": return False
        elif choice == "2": return True
        else: print("Please enter 1 or 2.")


def main():
    logger.info("Reachy Mini CPS Facilitator starting up.")
    print("\n=== Reachy Mini CPS Facilitator ===")
    print("LLM: Claude API (claude-haiku)" if USE_CLAUDE else "LLM: Ollama fallback")
    if not USE_CLAUDE:
        logger.warning("No ANTHROPIC_API_KEY — using Ollama.")

    check_mic()

    start_fresh = prompt_session_mode()
    if start_fresh:
        for f in [MEMORY_FILE, STAGE_FILE, SESSION_FILE]:
            if os.path.exists(f):
                try: os.remove(f)
                except IOError as e: logger.error(f"Could not clear {f}: {e}")
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

            # ── Shared state for VAD + Enter-to-speak ────────────────────────
            utterance_queue = __import__('queue').Queue()
            vad_listener    = None
            _awaiting_end   = False   # True after first end phrase detected

            def handle_utterance(text: str):
                """Callback from VAD — routes text into the main loop queue."""
                utterance_queue.put(text)

            # ── Startup ───────────────────────────────────────────────────────
            if USE_VAD:
                print("\nVAD active — just speak when you're ready.")
                print("(You can also press Enter at any time to use manual recording.)\n")
                vad_listener = VADListener(
                    input_device=REACHY_INPUT_DEVICE,
                    sample_rate=SAMPLE_RATE,
                    whisper_model=WHISPER_MODEL,
                    on_utterance=handle_utterance,
                    speak_fn=speak,
                    llm_call_fn=llm_call if USE_CLAUDE else None,
                    anthropic_api_key=ANTHROPIC_API_KEY,
                )
                vad_listener.start()
                # Put Reachy to sleep — wake phrase or Enter wakes it
                vad_listener.sleep()
                speak("I'm listening. Say 'Hey Reachy' whenever you're ready to begin, "
                      "or press Enter to start manually.")
            else:
                print("\nPress Enter and say you're ready to start the CPS process.")
                input()
                speak("Hey! I heard you — let's get started.")
                speak(random.choice(STAGE_GREETINGS[current_stage]))

            # ── Main conversation loop ────────────────────────────────────────
            while True:
                user_input = None

                if USE_VAD:
                    # Non-blocking check of VAD queue, with Enter fallback
                    import select, sys
                    print("\n(Speaking or press Enter for manual input | type 'quit' to exit)")
                    try:
                        # Poll every 0.2s for VAD input or keyboard
                        while user_input is None:
                            # Check VAD queue
                            try:
                                user_input = utterance_queue.get_nowait()
                            except __import__('queue').Empty:
                                pass

                            # Check if Enter was pressed (Windows-compatible)
                            if user_input is None:
                                import msvcrt
                                if msvcrt.kbhit():
                                    key = msvcrt.getwch()
                                    if key == '\r' or key == '\n':
                                        # Manual Enter-to-speak fallback
                                        if vad_listener:
                                            vad_listener.pause()
                                        typed = input("Type 'quit' or press Enter to record: ").strip().lower()
                                        if typed == 'quit':
                                            user_input = '__QUIT__'
                                        else:
                                            stop_idle()
                                            do_listening_pose(mini)
                                            user_input = record_audio() or ''
                                            if vad_listener:
                                                vad_listener.resume()
                                    elif key.lower() == 'q':
                                        user_input = '__QUIT__'

                            if user_input is None:
                                __import__('time').sleep(0.2)

                    except (EOFError, KeyboardInterrupt):
                        break
                else:
                    # Original Enter-to-speak mode
                    try:
                        cmd = input("\nPress Enter to speak (or type 'quit'): ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if cmd == 'quit':
                        user_input = '__QUIT__'
                    else:
                        stop_idle()
                        do_listening_pose(mini)
                        user_input = record_audio() or ''

                # ── Handle special signals ────────────────────────────────────
                if user_input == '__QUIT__':
                    stop_idle()
                    if vad_listener:
                        vad_listener.stop()
                    speak(generate_summary(current_session, current_stage))
                    speak("See you next time!")
                    break

                if user_input == '__CONSENT_YES__':
                    # VAD wake sequence confirmed — begin CPS
                    if vad_listener:
                        vad_listener.wake()
                    speak(random.choice(STAGE_GREETINGS[current_stage]))
                    continue

                if not user_input or not user_input.strip():
                    start_idle(mini)
                    continue

                # ── Pause VAD while processing ────────────────────────────────
                if vad_listener:
                    vad_listener.pause()

                stop_idle()

                if check_for_advance(user_input):
                    nxt = next_stage(current_stage)
                    if nxt:
                        current_stage = nxt
                        save_stage(current_stage)
                        ds.set_stage(current_stage)
                        logger.info(f"Advancing to: {current_stage}")
                        print(f"\n--- Stage: {stage_label(current_stage)} ---\n")
                        speak(random.choice(STAGE_GREETINGS[current_stage]))
                        chat(mini, current_session, past_context,
                             f"We just moved into the {stage_label(current_stage)} stage. "
                             f"Please acknowledge the transition warmly and open this stage "
                             f"with your first facilitation question.",
                             current_stage)
                    else:
                        logger.info("All stages complete.")
                        print("\n--- All stages complete! ---\n")
                        speak("We've made it through the whole process — amazing work!")
                        speak("I'll save our session now. It was a pleasure working through this with you!")
                        if vad_listener:
                            vad_listener.stop()
                        break
                    start_idle(mini)
                    if vad_listener:
                        vad_listener.resume()
                    continue

                # ── End session voice phrase ──────────────────────────────
                if _awaiting_end:
                    # User already said they want to end — check confirmation
                    lowered = user_input.lower()
                    if any(p in lowered for p in [
                        "let's end the session for today",
                        "lets end the session for today",
                        "end the session for today",
                        "yes", "yeah", "yep", "sure", "confirm"
                    ]):
                        if vad_listener: vad_listener.stop()
                        stop_idle()
                        speak(generate_summary(current_session, current_stage))
                        speak("It was great working through this with you. See you next time!")
                        break
                    else:
                        # They changed their mind
                        _awaiting_end = False
                        speak("No problem — let's keep going. What's on your mind?")
                        start_idle(mini)
                        if vad_listener: vad_listener.resume()
                        continue

                if check_for_end(user_input):
                    _awaiting_end = True
                    if vad_listener: vad_listener.pause()
                    speak(
                        "Of course. If you're sure, just say "
                        "'Let's end the session for today' and I'll save everything and wrap up."
                    )
                    if vad_listener: vad_listener.resume()
                    start_idle(mini)
                    continue

                chat(mini, current_session, past_context, user_input, current_stage)

                # Resume VAD after response
                if vad_listener:
                    vad_listener.resume()

    except ConnectionError as e:
        logger.critical(f"Could not connect: {e}")
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
        logger.info("Session saved.")
        print("\nSession saved. Goodbye!")


if __name__ == "__main__":
    main()