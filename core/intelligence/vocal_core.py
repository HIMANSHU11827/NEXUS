import logging
# Silence all noisy libraries
for logger in ["comtypes", "httpx", "urllib3", "speech_recognition"]:
    logging.getLogger(logger).setLevel(logging.ERROR)

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None
    
try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import threading
import queue
import io
import time
import os
import logging

# 🔇 [v18 SILENCE_NOISE]: Purge background neural heartbeats
logging.getLogger("faster_whisper").setLevel(logging.ERROR)
logging.getLogger("ctranslate2").setLevel(logging.ERROR)

class C:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    RESET = "\033[0m"

class NexusVocalCore:
    def __init__(self):
        self.msg_queue = queue.Queue()
        self.engine = None
        self.recognizer = sr.Recognizer() if sr else None
        self.mic = None
        self.driver_id = None
        self.whisper = None
        self._initialized = False
        
        # ⚡ [v18 PERMANENT_FIX]: Hardware Bridge Sync
        if sd:
            try:
                devices = sd.query_devices()
                for i, dev in enumerate(devices):
                    if dev['max_input_channels'] > 0 and 'Microphone Array' in dev['name']:
                        self.driver_id = i
                        break
                if self.driver_id is None:
                    for i, dev in enumerate(devices):
                        if dev['max_input_channels'] > 0:
                            self.driver_id = i
                            break
            except: pass
            
        threading.Thread(target=self._vocal_worker, daemon=True).start()

    def _vocal_worker(self):
        """Initializes engines and then processes the queue."""
        # 1. Initialize TTS
        if pyttsx3:
            try:
                import os
                if os.name == 'nt':
                    self.engine = pyttsx3.init('sapi5')
                else:
                    self.engine = pyttsx3.init()
                self._apply_voice_settings()
            except Exception as e:
                print(f"[VOCAL_ERROR]: TTS Engine failed: {e}")

    def _apply_voice_settings(self):
        """Calibrate text-to-speech for clear operator feedback."""
        if not self.engine: return
        try:
            voices = self.engine.getProperty('voices')
            # Prefer the first stable system voice.
            if len(voices) > 1:
                self.engine.setProperty('voice', voices[0].id)
            self.engine.setProperty('rate', 170)
        except: pass

        self._initialized = True
        # Notification is now handled by the shell or first command

        while True:
            try:
                text = self.msg_queue.get()
                if not text: 
                    self.msg_queue.task_done()
                    break
                
                # 🧼 Sanitization: Do not read code blocks or JSON out loud
                if "{" in text and "}" in text or "```" in text or "action" in text:
                    self.msg_queue.task_done()
                    continue
                
                # 🎙️ [v21.1 PERPETUAL_SAPI]: Subprocess TTS Isolation
                # pyttsx3 fundamentally deadlocks in threading. Spawning it isolated perfectly solves this.
                import sys
                import subprocess
                
                clean_text = text.replace('"', '').replace("'", "")
                script = f'''
import pyttsx3
try:
    engine = pyttsx3.init()
    engine.setProperty('rate', 170)
    engine.say("""{clean_text}""")
    engine.runAndWait()
except:
    pass
'''
                # Run the speech purely detached from our main daemon
                subprocess.run([sys.executable, "-c", script], timeout=20)
                
            except subprocess.TimeoutExpired:
                print(f"{C.BLUE}[SYS]: Isolated TTS engine timed out. Releasing queue.{C.RESET}")
            except Exception as e:
                print(f"[VOCAL_ERROR]: TTS Loop failure: {e}")
            finally:
                try: self.msg_queue.task_done()
                except: pass

    def speak(self, text: str):
        self.msg_queue.put(text)

    def listen(self) -> str:
        """High-Fidelity listening protocol via Whisper Neural Link."""
        if not self.recognizer:
            return "[VOCAL_ERROR]: Speech system offline."
            
        # ⚡ [LATE_BINDING]: Initialize Whisper at the last possible moment
        if WhisperModel and self.whisper is None:
            try:
                print(f"{C.GRAY}[SYSTEM]: Loading Whisper Neural Engine...{C.RESET}")
                self.whisper = WhisperModel("tiny", device="cpu", compute_type="int8")
            except Exception: pass

        if sd:
            try:
                fs = 44100
                seconds = 4 # Optimized for speed
                
                recording = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype='int16', device=self.driver_id)
                sd.wait()
                
                # 🎙️ [v21.5 SILENCE_GATE]: High-fidelity filter to block hallucinations
                peak = np.max(np.abs(recording))
                if peak < 1200: # Increased threshold for total silence
                    return "" 
                
                wb_io = io.BytesIO()
                wav.write(wb_io, fs, recording)
                wb_io.seek(0)
                
                text = ""
                try:
                    if self.whisper:
                        segments, info = self.whisper.transcribe(wb_io, beam_size=5)
                        text = "".join([s.text for s in segments]).strip()
                    else:
                        with sr.AudioFile(wb_io) as source:
                            audio = self.recognizer.record(source)
                            text = self.recognizer.recognize_google(audio)
                except Exception:
                    pass
                        
                if text and len(text) > 2:
                    return text
                return "" # Return empty if no coherent speech detected
            except Exception:
                return ""
                
        return "" # SILENT fallback instead of error text
