import pyaudio
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d['maxInputChannels'] > 0:
        print(f"{i}: {d['name']} — {int(d['defaultSampleRate'])}Hz")
p.terminate()
