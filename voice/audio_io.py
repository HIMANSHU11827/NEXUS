from __future__ import annotations

import queue
import threading
from collections import deque
from typing import Any, Optional
import numpy as np


class AudioUnavailable(RuntimeError):
    pass


class ContinuousSpeechSession:
    def __init__(
        self,
        audio_io: "AudioIO",
        max_seconds: float,
        silence_threshold: float,
        silence_timeout_seconds: float,
        min_speech_seconds: float,
        status_callback: Optional[callable] = None,
    ):
        self.audio_io = audio_io
        self.max_seconds = float(max_seconds)
        self.silence_threshold = float(silence_threshold)
        self.silence_timeout_seconds = float(silence_timeout_seconds)
        self.min_speech_seconds = float(min_speech_seconds)
        self.status_callback = status_callback
        self._segments: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.clear_pending()

    def pause_capture(self) -> None:
        self._pause_event.set()
        self.clear_pending()

    def resume_capture(self) -> None:
        self.clear_pending()
        self._pause_event.clear()
        self._emit_status("waiting")

    def clear_pending(self) -> None:
        while True:
            try:
                self._segments.get_nowait()
            except queue.Empty:
                return

    def read_utterance(self, timeout: Optional[float] = None) -> np.ndarray:
        try:
            return self._segments.get(timeout=timeout)
        except queue.Empty:
            return np.asarray([], dtype=np.float32)

    def _emit_status(self, state: str) -> None:
        if self.status_callback:
            self.status_callback(state)

    def _capture_loop(self) -> None:
        import torch

        self.audio_io._load_vad()
        sd = self.audio_io._sounddevice()
        stream_rate = self.audio_io.input_sample_rate
        silero_rate = 16000
        chunk_frames_silero = 512
        chunk_frames = max(512, int(chunk_frames_silero * stream_rate / silero_rate))
        max_frames = int(self.max_seconds * stream_rate)
        silence_limit_chunks = max(1, int(self.silence_timeout_seconds / (chunk_frames_silero / silero_rate)))
        min_speech_chunks = max(1, int(self.min_speech_seconds / (chunk_frames_silero / silero_rate)))

        def reset_state():
            return [], deque(maxlen=25), False, 0, 0

        captured, preroll, speech_started, chunks_since_speech, speech_chunks_count = reset_state()
        self._emit_status("waiting")

        with sd.InputStream(
            samplerate=stream_rate,
            channels=1,
            dtype="float32",
            device=self.audio_io.input_device,
            blocksize=chunk_frames,
        ) as stream:
            while not self._stop_event.is_set():
                chunk, _ = stream.read(chunk_frames)
                audio_chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)

                if self._pause_event.is_set():
                    captured, preroll, speech_started, chunks_since_speech, speech_chunks_count = reset_state()
                    continue

                if stream_rate != silero_rate:
                    audio_chunk_16k = self.audio_io._resample_if_needed(audio_chunk, stream_rate, silero_rate)
                else:
                    audio_chunk_16k = audio_chunk

                is_speech = False
                if self.audio_io._vad_model:
                    chunk_len = len(audio_chunk_16k)
                    if chunk_len >= chunk_frames_silero:
                        vad_input = audio_chunk_16k[:chunk_frames_silero]
                    else:
                        vad_input = np.pad(audio_chunk_16k, (0, chunk_frames_silero - chunk_len))
                    with torch.no_grad():
                        tensor_chunk = torch.from_numpy(vad_input)
                        prob = self.audio_io._vad_model(tensor_chunk, silero_rate).item()
                        is_speech = prob > 0.4
                else:
                    rms = np.sqrt(np.mean(audio_chunk**2))
                    is_speech = rms > self.silence_threshold

                utterance_complete = False
                if is_speech:
                    if not speech_started:
                        self._emit_status("hearing")
                        captured.extend(preroll)
                        preroll.clear()
                        speech_started = True
                    captured.append(audio_chunk)
                    speech_chunks_count += 1
                    chunks_since_speech = 0
                else:
                    if speech_started:
                        captured.append(audio_chunk)
                        chunks_since_speech += 1
                        current_silence_limit = silence_limit_chunks
                        if speech_chunks_count > 100:
                            current_silence_limit = int(silence_limit_chunks * 1.5)
                        if speech_chunks_count >= min_speech_chunks and chunks_since_speech >= current_silence_limit:
                            utterance_complete = True
                    else:
                        preroll.append(audio_chunk)

                total_frames = sum(len(part) for part in captured)
                if speech_started and total_frames >= max_frames:
                    utterance_complete = True

                if not utterance_complete:
                    continue

                if captured:
                    raw = np.concatenate(captured)
                    resampled = self.audio_io._resample_if_needed(raw, stream_rate)
                    if resampled.size:
                        self._segments.put(resampled)
                captured, preroll, speech_started, chunks_since_speech, speech_chunks_count = reset_state()
                self._emit_status("waiting")


class AudioIO:
    def __init__(self, input_device: Optional[int | str], output_device: Optional[int | str], sample_rate: int, volume: float = 1.0):
        self.input_device = self._resolve_device(input_device, want_input=True)
        self.output_device = self._resolve_device(output_device, want_input=False)
        self.sample_rate = sample_rate
        self.input_sample_rate = self._resolve_input_sample_rate(self.input_device, self.sample_rate)
        self.output_sample_rate = self._resolve_output_sample_rate(self.output_device, self.sample_rate)
        self.volume = max(0.0, min(float(volume), 2.0))
        self._play_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._vad_model = None
        self._vad_utils = None

    @staticmethod
    def _sounddevice():
        try:
            import sounddevice as sd
            return sd
        except ImportError as exc:
            raise AudioUnavailable("sounddevice is not installed. Install the voice extras first.") from exc

    @classmethod
    def _resolve_device(cls, configured_device: Optional[int | str], *, want_input: bool) -> Optional[int | str]:
        if configured_device not in (None, ""):
            return configured_device
        try:
            sd = cls._sounddevice()
        except AudioUnavailable:
            return configured_device
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception:
            return configured_device

        # Build ranked candidate list — hard-block WDM-KS which always errors on Windows
        WDM_KS_BLOCKED = {"wdm-ks", "ks", "wdm"}
        candidates = []
        for index, device in enumerate(devices):
            channels = int(device["max_input_channels"] if want_input else device["max_output_channels"])
            if channels <= 0:
                continue
            name = str(device["name"])
            lower_name = name.lower()
            hostapi_name = str(hostapis[device["hostapi"]]["name"]).lower()

            # Hard-skip WDM-KS — it always throws PaErrorCode -9999 on Windows
            if any(kw in hostapi_name for kw in WDM_KS_BLOCKED):
                continue
            # Skip stereo mix / virtual loopback for input
            if want_input and "stereo mix" in lower_name:
                continue

            score = 0
            # Prefer MME > WASAPI > DirectSound for input (DirectSound capture is silent on Windows)
            # Prefer DirectSound > MME > WASAPI for output
            if want_input:
                if "mme" in hostapi_name:
                    score += 100
                elif "wasapi" in hostapi_name:
                    score += 80
                elif "directsound" in hostapi_name:
                    score += 30
                elif "core audio" in hostapi_name or "alsa" in hostapi_name:
                    score += 100
            else:
                if "directsound" in hostapi_name:
                    score += 100
                elif "mme" in hostapi_name:
                    score += 80
                elif "wasapi" in hostapi_name:
                    score += 50
                elif "core audio" in hostapi_name or "alsa" in hostapi_name:
                    score += 100

            # Prefer real microphone/speaker by name
            if want_input and "microphone" in lower_name:
                score += 20
            if not want_input and ("speaker" in lower_name or "headphone" in lower_name):
                score += 20

            # Penalise mapper/primary aliases
            if "mapper" in lower_name or "primary sound" in lower_name:
                score -= 10

            candidates.append((score, index))

        # Sort best-first
        candidates.sort(key=lambda x: -x[0])

        # Walk candidates, return first that actually opens
        for score, index in candidates:
            try:
                if want_input:
                    rate = 16000
                    try:
                        sd.check_input_settings(device=index, samplerate=rate, channels=1, dtype="float32")
                    except Exception:
                        info = sd.query_devices(index)
                        rate = int(float(info.get("default_samplerate", 44100)))
                    # Actually attempt to open stream (only real test on Windows)
                    import sounddevice as _sd
                    with _sd.InputStream(device=index, samplerate=rate, channels=1, dtype="float32", blocksize=512):
                        pass
                else:
                    sd.check_output_settings(device=index, samplerate=16000, channels=1, dtype="float32")
                return index
            except Exception:
                continue

        return configured_device


    @classmethod
    def _resolve_input_sample_rate(cls, input_device: Optional[int | str], requested_rate: int) -> int:
        if input_device in (None, ""):
            return requested_rate
        try:
            sd = cls._sounddevice()
            sd.check_input_settings(device=input_device, samplerate=requested_rate, channels=1, dtype="float32")
            return requested_rate
        except Exception:
            try:
                device_info = sd.query_devices(input_device)
                fallback = int(float(device_info["default_samplerate"]))
                sd.check_input_settings(device=input_device, samplerate=fallback, channels=1, dtype="float32")
                return fallback
            except Exception:
                return requested_rate

    @classmethod
    def _resolve_output_sample_rate(cls, output_device: Optional[int | str], requested_rate: int) -> int:
        if output_device in (None, ""):
            return requested_rate
        try:
            sd = cls._sounddevice()
            sd.check_output_settings(device=output_device, samplerate=requested_rate, channels=1, dtype="float32")
            return requested_rate
        except Exception:
            try:
                device_info = sd.query_devices(output_device)
                fallback = int(float(device_info["default_samplerate"]))
                sd.check_output_settings(device=output_device, samplerate=fallback, channels=1, dtype="float32")
                return fallback
            except Exception:
                return requested_rate

    def _resample_if_needed(self, audio: Any, source_rate: int, target_rate: Optional[int] = None) -> Any:
        import numpy as np
        
        target_rate = target_rate or self.sample_rate
        if int(source_rate) == int(target_rate):
            return audio
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if len(samples) == 0:
            return samples
        duration = len(samples) / float(source_rate)
        target_len = max(1, int(round(duration * float(target_rate))))
        source_x = np.linspace(0.0, duration, num=len(samples), endpoint=False)
        target_x = np.linspace(0.0, duration, num=target_len, endpoint=False)
        return np.interp(target_x, source_x, samples).astype(np.float32)

    def record(self, seconds: float) -> Any:
        import numpy as np

        sd = self._sounddevice()
        frames = max(1, int(float(seconds) * self.input_sample_rate))
        audio = sd.rec(
            frames,
            samplerate=self.input_sample_rate,
            channels=1,
            dtype="float32",
            device=self.input_device,
        )
        sd.wait()
        return self._resample_if_needed(np.asarray(audio).reshape(-1), self.input_sample_rate)

    def _load_vad(self):
        if self._vad_model is not None:
            return
        try:
            import torch
            from silero_vad import load_silero_vad
            self._vad_model = load_silero_vad()
            # print("[voice] Neural VAD Engine Online.")
        except Exception as e:
            # print(f"[voice-warning] Neural VAD failed to load, using RMS fallback: {e}")
            self._vad_model = False

    def record_until_pause(
        self,
        max_seconds: float,
        silence_threshold: float,
        silence_timeout_seconds: float,
        min_speech_seconds: float,
        status_callback: Optional[callable] = None,
    ) -> Any:
        import torch
        self._load_vad()

        sd = self._sounddevice()
        # Use the device's native rate to avoid PortAudio rate-mismatch errors
        stream_rate = self.input_sample_rate
        silero_rate = 16000  # Silero always needs 16kHz
        # 512 samples at silero_rate = 32ms chunks as required by Silero
        chunk_frames_silero = 512
        # Scale blocksize to the native device rate
        chunk_frames = max(512, int(chunk_frames_silero * stream_rate / silero_rate))
        max_frames = int(float(max_seconds) * stream_rate)

        # Adaptive limits based on time
        silence_limit_chunks = int(float(silence_timeout_seconds) / (chunk_frames_silero / silero_rate))
        min_speech_chunks = int(float(min_speech_seconds) / (chunk_frames_silero / silero_rate))

        captured = []
        preroll = deque(maxlen=25)  # ~800ms of pre-buffer
        speech_started = False
        chunks_since_speech = 0
        speech_chunks_count = 0

        if status_callback:
            status_callback("waiting")

        with sd.InputStream(
            samplerate=stream_rate,
            channels=1,
            dtype="float32",
            device=self.input_device,
            blocksize=chunk_frames,
        ) as stream:
            while len(captured) * chunk_frames < max_frames:
                chunk, _ = stream.read(chunk_frames)
                audio_chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)

                # Resample chunk to 16kHz for Silero if needed
                if stream_rate != silero_rate:
                    audio_chunk_16k = self._resample_if_needed(audio_chunk, stream_rate, silero_rate)
                else:
                    audio_chunk_16k = audio_chunk

                is_speech = False
                if self._vad_model:
                    # Neural path — Silero needs exactly 512 samples at 16kHz
                    chunk_len = len(audio_chunk_16k)
                    if chunk_len >= chunk_frames_silero:
                        vad_input = audio_chunk_16k[:chunk_frames_silero]
                    else:
                        vad_input = np.pad(audio_chunk_16k, (0, chunk_frames_silero - chunk_len))
                    with torch.no_grad():
                        tensor_chunk = torch.from_numpy(vad_input)
                        prob = self._vad_model(tensor_chunk, silero_rate).item()
                        is_speech = prob > 0.4
                else:
                    # Fallback RMS path
                    rms = np.sqrt(np.mean(audio_chunk**2))
                    is_speech = rms > float(silence_threshold)

                if is_speech:
                    if not speech_started:
                        if status_callback:
                            status_callback("hearing")
                        captured.extend(preroll)
                        preroll.clear()
                        speech_started = True
                    captured.append(audio_chunk)
                    speech_chunks_count += 1
                    chunks_since_speech = 0
                else:
                    if speech_started:
                        captured.append(audio_chunk)
                        chunks_since_speech += 1

                        current_silence_limit = silence_limit_chunks
                        if speech_chunks_count > 100:
                            current_silence_limit = int(silence_limit_chunks * 1.5)

                        if speech_chunks_count >= min_speech_chunks and chunks_since_speech >= current_silence_limit:
                            break
                    else:
                        preroll.append(audio_chunk)

        if status_callback:
            status_callback("processing")

        if not speech_started or not captured:
            return np.asarray([], dtype=np.float32)

        # Concatenate at native rate then resample to the STT target rate
        raw = np.concatenate(captured)
        return self._resample_if_needed(raw, stream_rate)

    def open_continuous_session(
        self,
        max_seconds: float,
        silence_threshold: float,
        silence_timeout_seconds: float,
        min_speech_seconds: float,
        status_callback: Optional[callable] = None,
    ) -> ContinuousSpeechSession:
        session = ContinuousSpeechSession(
            self,
            max_seconds,
            silence_threshold,
            silence_timeout_seconds,
            min_speech_seconds,
            status_callback=status_callback,
        )
        session.start()
        return session


    def is_silent(self, audio: Any, threshold: float) -> bool:
        import numpy as np

        if audio.size == 0:
            return True
        return float(np.max(np.abs(audio))) < float(threshold)

    def stop_playback(self) -> None:
        self._stop_event.set()
        try:
            self._sounddevice().stop()
        except AudioUnavailable:
            pass

    def play(self, audio: Any, sample_rate: int) -> None:
        import numpy as np

        sd = self._sounddevice()
        if audio is None or len(audio) == 0:
            return
        with self._play_lock:
            self._stop_event.clear()
            samples = self._resample_if_needed(
                np.asarray(audio, dtype="float32").reshape(-1), 
                source_rate=sample_rate, 
                target_rate=self.output_sample_rate
            )
            samples = np.clip(samples * self.volume, -1.0, 1.0)
            sd.play(
                samples,
                samplerate=self.output_sample_rate,
                device=self.output_device,
                blocking=True,
            )
            if self._stop_event.is_set():
                sd.stop()
