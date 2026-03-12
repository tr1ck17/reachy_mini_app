import sounddevice as sd
import soundfile as sf
import numpy as np

DURATION = 5
SAMPLE_RATE = 16000

print("Recording for 5 seconds... speak now!")
audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32')
sd.wait()
sf.write("test_recording.wav", audio, SAMPLE_RATE)
print("Saved to test_recording.wav - play it back to verify!")