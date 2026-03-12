from faster_whisper import WhisperModel

model = WhisperModel("tiny", device="cpu", compute_type="int8")

print("Transcribing...")
segments, info = model.transcribe("test_recording.wav")

for segment in segments:
	print(f"[{segment.start:.1f}s -> {segment.end:.1f}s] {segment.text}")