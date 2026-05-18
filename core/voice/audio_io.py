from __future__ import annotations

import threading
from collections import deque
from typing import Any, Optional
import numpy as np


class AudioUnavailable(RuntimeError):
    pass


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

        best_index: Optional[int] = None
        best_score = -1
        for index, device in enumerate(devices):
            channels = int(device["max_input_channels"] if want_input else device["max_output_channels"])
            if channels <= 0:
                continue
            name = str(device["name"])
            hostapi_name = str(hostapis[device["hostapi"]]["name"]).lower()
            lower_name = name.lower()
            score = 0
            if "wasapi" in hostapi_name:
                score += 40
            if want_input and "microphone" in lower_name:
                score += 30
            if not want_input and ("speaker" in lower_name or "headphone" in lower_name):
                score += 30
            if want_input:
                try:
                    sd.check_input_settings(device=index, samplerate=16000, channels=1, dtype="float32")
                    score += 80
                except Exception:
                    pass
                try:
                    default_rate = int(float(device["default_samplerate"]))
                    if default_rate == 16000:
                        score += 25
                    elif default_rate in {32000, 44100, 48000}:
                        score += 5
                except Exception:
                    pass
            if "stereo mix" in lower_name:
                score -= 50
            if "mapper" in lower_name or "primary sound" in lower_name:
                score -= 10
            if score > best_score:
                best_score = score
                best_index = index
        return best_index if best_index is not None else configured_device

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
        stream_rate = 16000 # Silero prefers 16k
        # Use 512 samples (32ms) as required by Silero
        chunk_frames = 512 
        max_frames = int(float(max_seconds) * stream_rate)
        
        # Adaptive limits based on time
        silence_limit_chunks = int(float(silence_timeout_seconds) / (chunk_frames / stream_rate))
        min_speech_chunks = int(float(min_speech_seconds) / (chunk_frames / stream_rate))

        captured = []
        preroll = deque(maxlen=25) # Increased to ~800ms of pre-buffer for better context
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
                
                is_speech = False
                if self._vad_model:
                    # Neural path
                    with torch.no_grad():
                        tensor_chunk = torch.from_numpy(audio_chunk)
                        prob = self._vad_model(tensor_chunk, stream_rate).item()
                        is_speech = prob > 0.4 # Slightly more sensitive threshold
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
                        
                        # Adaptive silence: if user spoke for a long time, allow slightly more silence
                        current_silence_limit = silence_limit_chunks
                        if speech_chunks_count > 100: # Over ~3 seconds of speech
                            current_silence_limit = int(silence_limit_chunks * 1.5)
                        
                        if speech_chunks_count >= min_speech_chunks and chunks_since_speech >= current_silence_limit:
                            break
                    else:
                        preroll.append(audio_chunk)

        if status_callback:
            status_callback("processing")

        if not speech_started or not captured:
            return np.asarray([], dtype=np.float32)
            
        return self._resample_if_needed(np.concatenate(captured), stream_rate)

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
