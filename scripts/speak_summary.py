from core.voice import VoiceAssistant, VoiceSettings
from core.config_loader import NexusConfigLoader
import time

def main():
    print("[system] Initializing NEXUS Voice for summary...")
    settings = VoiceSettings.from_config(NexusConfigLoader())
    # Ensure audio is enabled for this run
    settings.enabled = True
    settings.auto_speak = True
    
    try:
        assistant = VoiceAssistant(settings)
        summary = (
            "NEXUS AI is our local-first autonomous engineering platform, designed for direct system control "
            "and intelligent coding workflows. We are currently architecting NOVA-150, a revolutionary 150-million "
            "parameter multimodal model. NOVA-150 replaces traditional attention with linear-time recurrence "
            "through the HELIX system, utilizes SPARK'S hardware-aware Mixture of Experts, and introduces "
            "PRISM for wavelet-based vision processing. Our goal is a universal AI engine that runs "
            "efficiently on any hardware, from NPUs to SSD-backed memory systems, all encapsulated in the "
            "precision-agnostic dot nova format."
        )
        
        print(f"\n[NEXUS Summary]:\n{summary}\n")
        print("[voice] Speaking summary...")
        assistant.speak(summary, blocking=True)
        print("[voice] Done.")
        
    except Exception as e:
        print(f"[error] Failed to run voice summary: {e}")

if __name__ == "__main__":
    main()
