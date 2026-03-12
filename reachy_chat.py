import asyncio
import ollama
import edge_tts
import sounddevice as sd
import soundfile as sf
import numpy as np
from faster_whisper import WhisperModel
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

MODEL = "llama3.2:3b"
WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
SAMPLE_RATE = 16000
RECORD_SECONDS = 5
VOICE = "en-US-AriaNeural"

SYSTEM_PROMPT = """You are Reachy Mini, a friendly, curious, and expressive small robot companion.
	You speak in short, warm, conversational sentences. Keep responses to 1-3 sentences. After
	your response, on a new line write:
	MOOD: [one of: happy, thinking, surprised, neutral]"""

def record_audio() -> str:
    import time
    print("🎤 Get ready...")
    time.sleep(1)
    print("🔴 Recording now! Speak!")
    audio = sd.rec(int(RECORD_SECONDS * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    
    volume = np.sqrt(np.mean(audio**2))
    print(f"Volume level: {volume:.4f}")
    
    if volume < 0.001:
        print("⚠️ Audio too quiet — check your mic!")
        return ""
    
    sf.write("input.wav", audio, SAMPLE_RATE)
    segments, _ = WHISPER_MODEL.transcribe("input.wav")
    text = " ".join(segment.text for segment in segments).strip()
    print(f"You: {text}")
    return text

def parse_response(raw: str):
	lines = raw.strip().split("\n")
	mood = "neutral"
	text_lines = []
	for line in lines:
		if line.startswith("MOOD:"):
			mood = line.replace("MOOD:", "").strip().lower()
		else:
			text_lines.append(line)
	return " ".join(text_lines).strip(), mood

def express_mood(mini, mood: str):
	if mood == "happy":
		mini.goto_target(antennas=[0.6, 0.6], duration=0.3)
		mini.goto_target(antennas=[0, 0], duration = 0.3)
	elif mood == "thinking":
		mini.goto_target(head=create_head_pose(roll=15, degrees=True), duration=0.5)
	elif mood == "surprised":
		mini.goto_target(head=create_head_pose(z=15, mm=True), duration=0.3)
		mini.goto_target(antennas=[0.8, 0.8], duration=0.2)
		mini.goto_target(antennas=[0, 0], duration=0.3)
	else:
		mini.goto_target(head=create_head_pose(), antennas=[0, 0], duration=0.5)

async def speak(text: str):
	communicate = edge_tts.Communicate(text, voice=VOICE)
	await communicate.save("response.wav")
	data, samplerate = sf.read("response.wav")
	sd.play(data, samplerate)
	sd.wait()

def chat(mini, history: list, user_message: str):
	history.append({"role": "user", "content": user_message})
	response = ollama.chat(
		model=MODEL,
		messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
	)
	raw = response["message"]["content"]
	text, mood = parse_response(raw)
	print(f"Reachy ({mood}): {text}")
	express_mood(mini, mood)
	asyncio.run(speak(text))
	history.append({"role": "assistant", "content": text})
	return text

def main():
	print("Reachy Mini is online! Press Enter to speak, 'quit' to exit.\n")
	history = []
	with ReachyMini() as mini:
		while True:
			cmd = input("Press Enter to speak (or type 'quit'): ").strip().lower()
			if cmd == "quit":
				print("Reachy: Goodbye!")
				asyncio.run(speak("Goodbye! It was great talking with you!"))
				break
			user_input = record_audio()
			if user_input:
				chat(mini, history, user_input)

if __name__ == "__main__":
	main()