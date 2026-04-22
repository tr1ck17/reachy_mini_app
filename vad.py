"""
vad.py
Voice Activity Detection for Reachy Mini CPS Facilitator.

Uses numpy RMS energy detection — no external VAD dependencies.
Runs as a background thread, continuously listens, and calls
on_utterance(text) when a complete utterance is detected.

TUNING GUIDE (if things aren't working):
- Speech not detected: lower SPEECH_THRESHOLD (try 0.01)
- Too much background noise triggering: raise SPEECH_THRESHOLD (try 0.03)
- Whisper hallucinating random words: raise NO_SPEECH_THRESHOLD (try 0.6)
- Wake phrase not triggering: check WAKE_PHRASES list, Whisper mishears are common
- Utterance cut off too early: raise SILENCE_DURATION (try 2.5)
- Utterance waits too long: lower SILENCE_DURATION (try 1.2)
"""

import logging
import os
import queue
import re
import threading
import time
import uuid

import numpy as np
import sounddevice as sd
import soundfile as sf

logger = logging.getLogger(__name__)

# ── Wake phrases ──────────────────────────────────────────────────────────────
# All lowercase, no punctuation — matched against stripped Whisper output

WAKE_PHRASES = [
    "hey reachy",
    "wake up",
    "daddys home",
    "daddy's home",
    "hey ready",      # common whisper mishear
    "hey richie",     # common whisper mishear
    "hey ritchie",    # common whisper mishear
    "hey reggie",     # common whisper mishear
    "a reggie",       # common whisper mishear
    "hey regi",       # common whisper mishear
    "hey rich",       # common whisper mishear
    "hey reach",      # common whisper mishear
    "okay reachy",
    "yo reachy",
    "reachy",
    "richie",
    "reggie",
    "hey reachie",
    "let's go reachy",
    "lets go reachy",
    "rise and shine",
    "wakey wakey",
]

CONSENT_YES = [
    "yes", "yeah", "yep", "yup", "sure", "ready", "lets go", "let's go",
    "absolutely", "definitely", "of course", "go ahead", "start", "begin",
    "im ready", "i'm ready", "lets begin", "let's begin",
]

CONSENT_NO = [
    "no", "nope", "not yet", "not now", "wait", "later", "hold on",
    "give me a minute", "give me a second", "not ready",
]

# ── Tunable Config ────────────────────────────────────────────────────────────

LISTEN_SAMPLE_RATE = 44100   # must match device native rate
CHUNK_SIZE         = 2048    # samples per chunk (~46ms at 44100Hz)

# ↓ Raise if background noise triggers false detections (try 0.02, 0.03)
# ↓ Lower if your voice isn't being picked up (try 0.01)
SPEECH_THRESHOLD   = 0.018

# Seconds of silence after speech before treating utterance as done
SILENCE_DURATION   = 2.0

# Minimum seconds of speech to bother transcribing (filters out clicks/noise)
MIN_SPEECH_DURATION = 0.5

# Whisper no_speech_prob above this = hallucination, discard the transcript
# ↑ Raise if Whisper keeps making up words during silence (try 0.7, 0.8)
NO_SPEECH_THRESHOLD = 0.5

# Seconds of silence before Reachy checks in ("Still there?")
CHECKIN_TIMEOUT    = 18.0

# Seconds to wait for response after check-in before giving up
CHECKIN_WAIT       = 5.0


def _strip_punct(text: str) -> str:
    """Remove punctuation and lowercase — for reliable phrase matching."""
    return re.sub(r'[^\w\s]', '', text.lower()).strip()


class VADListener:
    """
    Continuous voice activity detection using RMS energy.

    Background thread listens continuously via sounddevice.
    Detects speech start/end using volume thresholds.
    Transcribes with Whisper, filters hallucinations via no_speech_prob.
    Calls on_utterance(text) with each complete utterance.
    """

    def __init__(
        self,
        input_device: int,
        sample_rate: int,
        whisper_model,
        on_utterance,
        speak_fn,
        llm_call_fn=None,
        anthropic_api_key: str = None,
    ):
        self.input_device    = input_device
        self.sample_rate     = sample_rate
        self.whisper_model   = whisper_model
        self.on_utterance    = on_utterance
        self.speak           = speak_fn
        self.llm_call_fn     = llm_call_fn
        self.anthropic_key   = anthropic_api_key

        self._audio_queue    = queue.Queue()
        self._stop_event     = threading.Event()
        self._paused         = threading.Event()
        self._asleep         = threading.Event()
        self._thread         = None
        self._last_speech_at = time.time()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("VAD listener started.")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("VAD listener stopped.")

    def pause(self):
        """Call before Reachy speaks — prevents picking up its own voice."""
        self._paused.set()
        # Drain the queue so old audio doesn't trigger after resume
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def resume(self):
        """Call after Reachy finishes speaking."""
        self._paused.clear()
        self._last_speech_at = time.time()

    def sleep(self):
        """Enter sleep mode — only wake phrases activate Reachy."""
        self._asleep.set()
        logger.info("VAD: sleeping — waiting for wake phrase.")

    def wake(self):
        """Exit sleep mode — actively listening for CPS conversation."""
        self._asleep.clear()
        self._last_speech_at = time.time()
        logger.info("VAD: awake.")

    @property
    def is_sleeping(self):
        return self._asleep.is_set()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self):
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SIZE,
                device=self.input_device,
                callback=self._audio_callback,
            ):
                logger.info("VAD audio stream open.")
                self._listen_loop()
        except Exception as e:
            logger.error(f"VAD stream error: {e}")

    def _audio_callback(self, indata, frames, time_info, status):
        if not self._paused.is_set():
            self._audio_queue.put(indata.copy().flatten())

    def _rms(self, chunk: np.ndarray) -> float:
        return float(np.sqrt(np.mean(chunk ** 2)))

    def _listen_loop(self):
        in_speech     = False
        speech_chunks = []
        silence_start = None

        while not self._stop_event.is_set():

            # Silence timeout check-in
            if (not in_speech and
                not self._paused.is_set() and
                not self._asleep.is_set() and
                time.time() - self._last_speech_at > CHECKIN_TIMEOUT):
                self._do_checkin()
                continue

            try:
                chunk = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._paused.is_set():
                # Drain while paused
                while not self._audio_queue.empty():
                    try:
                        self._audio_queue.get_nowait()
                    except queue.Empty:
                        break
                in_speech     = False
                speech_chunks = []
                silence_start = None
                continue

            volume = self._rms(chunk)

            if not in_speech:
                if volume > SPEECH_THRESHOLD:
                    in_speech            = True
                    speech_chunks        = [chunk]
                    silence_start        = None
                    self._last_speech_at = time.time()
                    logger.debug(f"VAD: speech start (vol={volume:.4f})")
            else:
                speech_chunks.append(chunk)

                if volume > SPEECH_THRESHOLD:
                    silence_start        = None
                    self._last_speech_at = time.time()
                else:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= SILENCE_DURATION:
                        # Utterance ended
                        audio    = np.concatenate(speech_chunks)
                        duration = len(audio) / self.sample_rate
                        logger.debug(f"VAD: utterance ended ({duration:.1f}s)")

                        in_speech     = False
                        speech_chunks = []
                        silence_start = None

                        if duration >= MIN_SPEECH_DURATION:
                            self._handle_audio(audio)

    def _handle_audio(self, audio: np.ndarray):
        """Transcribe and route to wake handler or active conversation."""
        text, is_hallucination = self._transcribe(audio)

        if is_hallucination or not text:
            logger.debug(f"VAD: discarding transcription (hallucination or empty)")
            return

        if self._asleep.is_set():
            stripped = _strip_punct(text)
            if any(phrase in stripped for phrase in WAKE_PHRASES):
                logger.info(f"VAD: wake phrase in '{text}'")
                self.wake()
                self._do_wake_sequence()
            else:
                logger.debug(f"VAD: sleeping, no wake phrase in '{stripped}'")
        else:
            if self._is_complete(text):
                self.on_utterance(text)
            else:
                # Wait a bit more then dispatch anyway
                logger.debug("VAD: utterance may be incomplete, waiting 3s")
                extra = []
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    try:
                        extra.append(self._audio_queue.get(timeout=0.1))
                    except queue.Empty:
                        pass
                if extra:
                    full = np.concatenate([audio] + extra)
                    longer, _ = self._transcribe(full)
                    if longer:
                        text = longer
                self.on_utterance(text)

    def _transcribe(self, audio: np.ndarray) -> tuple[str, bool]:
        """
        Transcribe audio using Deepgram Nova-2 if available, else Whisper.
        Returns (text, is_hallucination).
        """
        filepath = f"vad_{uuid.uuid4().hex[:8]}.wav"
        try:
            sf.write(filepath, audio, self.sample_rate)

            # ── Deepgram STT ──────────────────────────────────────────────────
            deepgram_key = os.environ.get("DEEPGRAM_API_KEY")
            if deepgram_key:
                try:
                    from deepgram import DeepgramClient, PrerecordedOptions
                    dg = DeepgramClient(deepgram_key)
                    with open(filepath, "rb") as f:
                        audio_data = {"buffer": f.read(), "mimetype": "audio/wav"}
                    options = PrerecordedOptions(
                        model="nova-2",
                        language="en",
                        smart_format=True,
                    )
                    response = dg.listen.prerecorded.v("1").transcribe_file(audio_data, options)
                    text = response.results.channels[0].alternatives[0].transcript.strip()
                    confidence = response.results.channels[0].alternatives[0].confidence
                    if confidence < 0.4:
                        logger.debug(f"VAD: low confidence ({confidence:.2f}) — discarding")
                        return "", True
                    if text:
                        logger.info(f"VAD transcribed (Deepgram): {text}")
                        print(f"You: {text}")
                    return text, False
                except Exception as e:
                    logger.warning(f"Deepgram STT failed ({e}) — falling back to Whisper")

            # ── Whisper fallback ──────────────────────────────────────────────
            segments, info = self.whisper_model.transcribe(
                filepath,
                language="en",
                condition_on_previous_text=False,
            )
            segments = list(segments)

            if not segments:
                return "", False

            avg_no_speech = sum(s.no_speech_prob for s in segments) / len(segments)
            if avg_no_speech > NO_SPEECH_THRESHOLD:
                logger.debug(f"VAD: hallucination detected (no_speech_prob={avg_no_speech:.2f})")
                return "", True

            text = " ".join(s.text for s in segments).strip()
            if text:
                logger.info(f"VAD transcribed (Whisper): {text}")
                print(f"You: {text}")
            return text, False

        except Exception as e:
            logger.error(f"VAD transcription error: {e}")
            return "", False
        finally:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass

    def _is_complete(self, text: str) -> bool:
        """
        Ask Claude if utterance is complete or cut off mid-sentence.
        Falls back to True (treat as complete) if unavailable.
        """
        if not self.anthropic_key or not text:
            return True
        try:
            import anthropic as _anthropic
            client = _anthropic.Anthropic(api_key=self.anthropic_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                system=(
                    "You judge if a spoken utterance is complete or was cut off. "
                    "Reply only: 'yes' if complete, 'no' if cut off mid-sentence."
                ),
                messages=[{
                    "role": "user",
                    "content": f'Complete? "{text}"'
                }],
            )
            return response.content[0].text.strip().lower().startswith("y")
        except Exception as e:
            logger.warning(f"Completeness check failed ({e}) — treating as complete")
            return True

    def _do_wake_sequence(self):
        """Ask if user is ready to begin CPS after wake phrase detected."""
        self.pause()
        self.speak("Hey! Are you ready to begin the Creative Problem Solving process?")
        self.resume()

        # Listen for yes/no for up to 10 seconds
        speech_chunks = []
        in_speech     = False
        silence_start = None
        deadline      = time.time() + 10.0

        while time.time() < deadline and not self._stop_event.is_set():
            try:
                chunk = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._paused.is_set():
                continue

            volume = self._rms(chunk)

            if not in_speech:
                if volume > SPEECH_THRESHOLD:
                    in_speech     = True
                    speech_chunks = [chunk]
                    silence_start = None
            else:
                speech_chunks.append(chunk)
                if volume <= SPEECH_THRESHOLD:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= 1.0:
                        break
                else:
                    silence_start = None

        if not speech_chunks:
            logger.info("VAD: no consent response — going back to sleep")
            self.sleep()
            return

        audio = np.concatenate(speech_chunks)
        text, is_hallucination = self._transcribe(audio)

        if is_hallucination or not text:
            self.pause()
            self.speak("I didn't catch that — just say yes or no.")
            self.resume()
            self._do_wake_sequence()
            return

        stripped = _strip_punct(text)

        if any(w in stripped for w in CONSENT_YES):
            logger.info("VAD: consent YES")
            self.on_utterance("__CONSENT_YES__")
        elif any(w in stripped for w in CONSENT_NO):
            logger.info("VAD: consent NO")
            self.pause()
            self.speak("No problem — I'll be right here whenever you're ready.")
            self.resume()
            self.sleep()
        else:
            # Unclear response — try again
            self.pause()
            self.speak("Just say yes if you're ready, or no if you'd like to wait.")
            self.resume()
            self._do_wake_sequence()

    def _do_checkin(self):
        """Check in after long silence."""
        self._last_speech_at = time.time()
        self.pause()
        self.speak("Still there? Take your time — I'm right here.")
        self.resume()

        # Wait briefly for any audio response
        deadline = time.time() + CHECKIN_WAIT
        while time.time() < deadline:
            try:
                chunk = self._audio_queue.get(timeout=0.1)
                if self._rms(chunk) > SPEECH_THRESHOLD:
                    self._last_speech_at = time.time()
                    logger.info("VAD: user responded to check-in")
                    return
            except queue.Empty:
                continue

        logger.info("VAD: no response to check-in — continuing to wait")