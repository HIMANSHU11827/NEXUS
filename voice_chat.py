"""Run NEXUS in local voice-assistant mode."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import warnings

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import logging
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)

import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*You are sending unauthenticated requests to the HF Hub.*")
warnings.filterwarnings("ignore", message=".*TypedStorage is deprecated.*")

from core.config_loader import NexusConfigLoader
from core.voice import VoiceAssistant, VoiceSettings

import subprocess
import signal

def cleanup_voice_processes():
    """Ensure no other voice_chat.py instances are competing for audio/memory."""
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmd = proc.info.get('cmdline') or []
                if 'voice_chat.py' in " ".join(cmd) and proc.info['pid'] != current_pid:
                    print(f"[voice-system] Cleaning up stale voice session (PID: {proc.info['pid']})...")
                    os.kill(proc.info['pid'], signal.SIGTERM)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        pass


def wait_for_push_to_talk(key: str) -> None:
    if not key or key.lower() == "enter":
        return
    try:
        import keyboard
    except ImportError:
        input(f"keyboard is not installed for '{key}' push-to-talk. Press Enter to record...")
        return
    print(f"[voice] Press {key} to record. Ctrl+C exits.")
    keyboard.wait(key)
    time.sleep(0.1)


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS voice assistant using local Whisper-compatible STT and KittenTTS.")
    parser.add_argument("--text", action="store_true", help="Use typed text instead of microphone input.")
    parser.add_argument("--manual", action="store_true", help="Wait for Enter/push-to-talk before each recording.")
    parser.add_argument("--warmup", action="store_true", help="Load STT and TTS models before the first turn.")
    parser.add_argument("--once", action="store_true", help="Run one turn and exit.")
    parser.add_argument("--no-speak", action="store_true", help="Print replies without loading or playing TTS.")
    parser.add_argument("--message", type=str, default=None, help="Message to send (reads from stdin if not provided).")
    args = parser.parse_args()

    # cleanup_voice_processes()
    # print("[debug] Loading config...")
    settings = VoiceSettings.from_config(NexusConfigLoader())
    if args.no_speak:
        settings.auto_speak = False
    
    # print("[debug] Initializing VoiceAssistant...")
    try:
        check_system_health()
        assistant = VoiceAssistant(settings)
    except Exception as e:
        print(f"[voice-error] Initialization failed: {e}")
        return
    print("[voice] Assistant ready.")
    print(
        f"[voice] devices: input={assistant.audio.input_device!r} "
        f"output={assistant.audio.output_device!r} "
        f"capture_rate={assistant.audio.input_sample_rate}Hz "
        f"stt_rate={assistant.settings.sample_rate}Hz "
        f"playback_rate={assistant.audio.output_sample_rate}Hz"
    )
    if not settings.enabled:
        print("[voice] voice.enabled is false; explicit voice_chat.py run overrides the setting for this session.")
    if args.warmup:
        print("[voice] Loading Whisper and KittenTTS...")
        assistant.warmup()
        print("[voice] Ready.")

    if args.message is not None:
        reply = assistant.ask_text(args.message)
        print(f"NEXUS: {reply}")
        return

    if not sys.stdin.isatty():
        message = sys.stdin.read().strip()
        if message:
            reply = assistant.ask_text(message)
            print(f"NEXUS: {reply}")
            return

    if args.text:
        print("[voice] Text fallback mode. Type /stop to interrupt speech, /exit to quit.")
        run_text_loop(assistant, settings, args.once)
        return

    if args.manual:
        print("[voice] Manual voice mode. Press Enter/push-to-talk for each recording, /exit to quit.")
        assistant.speak("Welcome back sir, how may I assist you today?", blocking=False)
        run_manual_voice_loop(assistant, settings, args.once)
        return

    import time
    time.sleep(0.5)
    assistant.speak("Initializing.", blocking=True)
    assistant.speak("Welcome back sir, how may I assist you today?", blocking=True)
    run_auto_voice_loop(assistant, settings, args.once)


def print_turn(user_text: str, reply: str, spoken: bool, settings: VoiceSettings) -> None:
    if reply:
        print(f"NEXUS: {reply}")
        if settings.auto_speak and not spoken:
            print("[voice] TTS unavailable; text-only reply shown.")


def run_text_loop(assistant: VoiceAssistant, settings: VoiceSettings, once: bool) -> None:
    while True:
        try:
            typed = input("voice> ").strip()
        except (KeyboardInterrupt, EOFError):
            assistant.stop_speaking()
            print("\n[voice] stopped.")
            return
        if typed.lower() in {"/exit", "exit", "quit"}:
            assistant.stop_speaking()
            return
        if typed.lower() in {"/stop", "stop"}:
            assistant.stop_speaking()
            continue
        try:
            reply = assistant.ask_text(typed)
            spoken = assistant.speak(reply, blocking=False)
            print_turn(typed, reply, spoken, settings)
        except Exception as exc:
            print(f"[voice-error] {exc}", file=sys.stderr)
        if once:
            return


def run_manual_voice_loop(assistant: VoiceAssistant, settings: VoiceSettings, once: bool) -> None:
    while True:
        try:
            typed = input("voice> ").strip()
        except (KeyboardInterrupt, EOFError):
            assistant.stop_speaking()
            print("\n[voice] stopped.")
            return
        if typed.lower() in {"/exit", "exit", "quit"}:
            assistant.stop_speaking()
            return
        if typed.lower() in {"/stop", "stop"}:
            assistant.stop_speaking()
            continue
        try:
            if typed:
                reply = assistant.ask_text(typed)
                spoken = assistant.speak(reply, blocking=False)
                print_turn(typed, reply, spoken, settings)
            else:
                wait_for_push_to_talk(settings.push_to_talk_key)
                print("[voice] listening...")
                user_text, reply, spoken = assistant.voice_turn(speech_blocking=True)
                print_turn(user_text, reply, spoken, settings)
        except Exception as exc:
            print(f"[voice-error] {exc}", file=sys.stderr)
        if once:
            return


def check_system_health() -> None:
    """Check for memory pressure and stale Java processes."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            print(f"[voice-warning] High memory pressure ({mem.percent}%). Voice mode may be slow or unstable.")
        
        java_procs = [p for p in psutil.process_iter(['name']) if 'java' in (p.info['name'] or '').lower()]
        if len(java_procs) > 2:
            print(f"[voice-info] Detected {len(java_procs)} Java processes. Consider closing the Java Language Server if you experience hangs.")
    except Exception:
        pass


def run_auto_voice_loop(assistant: VoiceAssistant, settings: VoiceSettings, once: bool) -> None:
    import sys

    def status_cb(state: str):
        if state == "waiting":
            sys.stdout.write("\r\033[K[voice] Waiting for speech...")
        elif state == "hearing":
            sys.stdout.write("\r\033[K[voice] Hearing speech...  ")
        elif state == "processing":
            sys.stdout.write("\r\033[K[voice] Processing...      ")
        sys.stdout.flush()

    while True:
        try:
            user_text, reply, spoken = assistant.voice_turn(
                prompt_text_fallback=False,
                speech_blocking=True,
                status_callback=status_cb
            )
            
            if user_text:
                # Clear the status line before printing the transcription
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
                print(f"You: {user_text}")
                print_turn(user_text, reply, spoken, settings)
            else:
                # Silent turn, loop back
                pass
        except KeyboardInterrupt:
            assistant.stop_speaking()
            print("\n[voice] stopped.")
            return
        except Exception as exc:
            if settings.allow_text_fallback:
                print(f"\r\033[K[voice-error] {exc}", file=sys.stderr)
                print("[voice] STT failed. Restart with --text for typed fallback.")
            else:
                print(f"\r\033[K[voice-error] {exc}", file=sys.stderr)
        if once:
            return


if __name__ == "__main__":
    main()
