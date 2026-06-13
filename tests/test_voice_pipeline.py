import unittest

from voice.config import VoiceSettings
from voice.tts import sentence_chunks


class TestVoicePipeline(unittest.TestCase):
    def test_sentence_chunks_splits_long_replies_without_empty_chunks(self):
        text = "Hello there. " + " ".join(["word"] * 90) + "! Done."
        chunks = sentence_chunks(text, max_chars=80)
        self.assertTrue(chunks)
        self.assertTrue(all(chunks))
        self.assertTrue(all(len(chunk) <= 90 for chunk in chunks))
        self.assertIn("Hello there.", chunks[0])

    def test_voice_settings_loads_known_config_keys(self):
        class FakeConfig:
            def get(self, path, default=None):
                if path == "voice":
                    return {
                        "enabled": True,
                        "whisper_model": "models/local/voice/distil-whisper-large-v3",
                        "kitten_model": "KittenML/kitten-tts-micro-0.8",
                        "voice_name": "Luna",
                        "speech_speed": 1.2,
                    }
                return default

        settings = VoiceSettings.from_config(FakeConfig())
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.voice_name, "Luna")
        self.assertEqual(settings.speech_speed, 1.2)


if __name__ == "__main__":
    unittest.main()
