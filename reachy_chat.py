import asyncio
import time
import ollama
import edge_tts
import sounddevice as sd
import soundfile as sf
import numpy as np
from faster_whisper import WhisperModel
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
from cps_manager import build_system_prompt, check_for_advance, next_stage, stage_label, STAGES
from memory_manager import (
    load_memory, build_history_context, start_session,
    append_to_session, close_session
)

# -- Config
MODEL          = "llama3.2:3b"
WHISPER_MODEL  = WhisperModel("tiny", device="cpu", compute_type="int8")
SAMPLE_RATE    = 16000
RECORD_SECONDS = 7
VOICE          = "en-US-AriaNeural"

BASE_SYSTEM_PROMPT = """You are Reachy Mini, a friendly, curious, and expressive small robot companion
and Creative Problem Solving facilitator. You speak in short, warm, conversational sentences.
Keep responses to 1-3 sentences unless you need more to facilitate effectively.
You have memory of past conversations and may reference them naturally when relevant.
After your response, on a new line write:
MOOD: [one of: happy, thinking, surprised, neutral]
If you believe it is time to transition to the next CPS stage, also write on a new line:
ADVANCE: yes"""


# -- TTS
async def _speak_async(text: str):
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save("response.wav")

def speak(text: str):
    asyncio.run(_speak_async(text))
    data, samplerate = sf.read("response.wav")
    sd.play(data, samplerate)
    sd.wait()


# -- Expressions
def express_mood(mini, mood: str):
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


# -- Response parsing
def parse_response(raw: str):
    lines = raw.strip().split("\n")
    mood = "neutral"
    advance = False
    text_lines = []
    for line in lines:
        if line.startswith("MOOD:"):
            mood = line.replace("MOOD:", "").strip().lower()
        elif line.startswith("ADVANCE:"):
            advance = "yes" in line.lower()
        else:
            text_lines.append(line)
    return " ".join(text_lines).strip(), mood, advance


# -- Audio
def record_audio() -> str:
    print("Get ready...")
    time.sleep(0.5)
    print("Listening...")
    audio = sd.rec(int(RECORD_SECONDS * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=1, dtype="float32")
    sd.wait()
    volume = np.sqrt(np.mean(audio**2))
    if volume < 0.001:
        print("Too quiet, try again.")
        return ""
    sf.write("input.wav", audio, SAMPLE_RATE)
    segments, _ = WHISPER_MODEL.transcribe("input.wav")
    text = " ".join(s.text for s in segments).strip()
    print(f"You: {text}")
    return text


# -- Main chat
def chat(mini, current_session: dict, past_context: list,
         user_message: str, current_stage: str):

    system_prompt = build_system_prompt(current_stage, BASE_SYSTEM_PROMPT)

    # Build full message list: past context + current session history + new message
    append_to_session(current_session, "user", user_message)
    messages = past_context + current_session["history"]

    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "system", "content": system_prompt}] + messages,
    )
    raw = response["message"]["content"]
    text, mood, advance = parse_response(raw)

    print(f"Reachy ({mood}) [{stage_label(current_stage)}]: {text}")
    express_mood(mini, mood)
    speak(text)

    append_to_session(current_session, "assistant", text)
    return advance


def main():
    # Load memory
    sessions        = load_memory()
    past_context    = build_history_context(sessions)
    current_session = start_session()
    current_stage   = STAGES[0]

    print("Reachy Mini CPS Facilitator\n")
    print(f"Starting stage: {stage_label(current_stage)}")
    print(f"Loaded {len(sessions)} past session(s) from memory.\n")

    with ReachyMini() as mini:
        speak("Hey there! I'm here whenever you're ready to talk. What's on your mind?")

        try:
            while True:
                cmd = input("Press Enter to speak (or type 'quit'): ").strip().lower()
                if cmd == "quit":
                    speak("It was great thinking with you. See you next time!")
                    break

                user_input = record_audio()
                if not user_input:
                    continue

                user_wants_advance = check_for_advance(user_input)
                advance_suggested  = chat(mini, current_session, past_context,
                                          user_input, current_stage)

                if user_wants_advance or advance_suggested:
                    nxt = next_stage(current_stage)
                    if nxt:
                        current_stage = nxt
                        print(f"\n--- Moving to stage: {stage_label(current_stage)} ---\n")
                        speak(f"Let's move into the {stage_label(current_stage)} stage!")
                    else:
                        print("\n--- All stages complete! ---\n")
                        speak("We've made it through the whole process — amazing work!")

        except KeyboardInterrupt:
            print("\nShutting down...")

        finally:
            # Always save session on exit, even if Ctrl+C
            close_session(sessions, current_session)
            print("Session saved to memory.")


if __name__ == "__main__":
    main()