import asyncio
import edge_tts
import sounddevice as sd
import soundfile as sf

async def speak(text: str):
	communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
	await communicate.save("test_tts.wav")
	data, samplerate = sf.read("test_tts.wav")
	sd.play(data, samplerate)
	sd.wait()

asyncio.run(speak("Hi! I'm Reachy Mini, your robot companion. It's great to meet you!"))