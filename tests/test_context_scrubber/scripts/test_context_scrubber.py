__version__ = "1.0.0"

from nexus.common.context_scrubber import MessageSanitizer, StreamingContextScrubber


class TestStreamingContextScrubber:
    def test_clean_once_removes_thinking(self):
        r = StreamingContextScrubber.clean_once("Hello <thinking>internal</thinking> world")
        assert "internal" not in r
        assert "Hello" in r
        assert "world" in r

    def test_clean_once_removes_memory_context(self):
        r = StreamingContextScrubber.clean_once("x <memory-context>secret</memory-context> y")
        assert "secret" not in r

    def test_clean_once_removes_scratchpad(self):
        r = StreamingContextScrubber.clean_once("a <scratchpad>hidden</scratchpad> b")
        assert "hidden" not in r

    def test_clean_once_removes_task_complete(self):
        r = StreamingContextScrubber.clean_once("Done. TASK_COMPLETE")
        assert r == "Done."

    def test_clean_once_removes_truncation(self):
        r = StreamingContextScrubber.clean_once("text [TRUNCATED at 1000]")
        assert "TRUNCATED" not in r

    def test_clean_once_removes_control_chars(self):
        r = StreamingContextScrubber.clean_once("a\x00b\x01c")
        assert r == "abc"

    def test_clean_once_removes_surrogates(self):
        r = StreamingContextScrubber.clean_once("hello\ud800world")
        assert r == "helloworld"

    def test_feed_normal_text(self):
        s = StreamingContextScrubber()
        r = s.feed("Hello world")
        assert r == "Hello world"
        assert s.flush() == ""

    def test_feed_chunk_boundary_thinking(self):
        s = StreamingContextScrubber()
        r1 = s.feed("Hello <think")
        r2 = s.feed("ing>hidden</thinking> world")
        r3 = s.flush()
        assert r1 + r2 + r3 == "Hello  world"

    def test_feed_chunk_boundary_close_tag(self):
        s = StreamingContextScrubber()
        r1 = s.feed("<thinking>")
        r2 = s.feed("hidden")
        r3 = s.feed("</think")
        r4 = s.feed("ing>visible")
        r5 = s.flush()
        assert r1 + r2 + r3 + r4 + r5 == "visible"

    def test_unclosed_span_discarded(self):
        s = StreamingContextScrubber()
        r1 = s.feed("before ")
        r2 = s.feed("<thinking>never closed")
        r3 = s.flush()
        assert r1 + r2 + r3 == "before "

    def test_multiple_spans(self):
        s = StreamingContextScrubber()
        r1 = s.feed("a ")
        r2 = s.feed("<thinking>x</thinking> b ")
        r3 = s.feed("<scratchpad>y</scratchpad> c")
        assert r1 + r2 + r3 == "a  b  c"

    def test_nested_like_tags(self):
        s = StreamingContextScrubber()
        r1 = s.feed("<thinking>")
        r2 = s.feed("nested <scratchpad>test</scratchpad>")
        r3 = s.feed("</thinking>ok")
        assert r1 + r2 + r3 == "ok"

    def test_reset(self):
        s = StreamingContextScrubber()
        s.feed("<thinking>")
        s.reset()
        r = s.feed("visible")
        assert r == "visible"

    def test_clean_once_no_tags(self):
        r = StreamingContextScrubber.clean_once("Plain text with no tags")
        assert r == "Plain text with no tags"

    def test_clean_once_empty(self):
        assert StreamingContextScrubber.clean_once("") == ""


class TestMessageSanitizer:
    def test_sanitize_removes_cr(self):
        msg = {"role": "user", "content": "hello\r\nworld"}
        result = MessageSanitizer.sanitize_message(msg)
        assert result["content"] == "hello\nworld"

    def test_sanitize_removes_control_chars(self):
        msg = {"role": "user", "content": "a\x00b\x01c"}
        result = MessageSanitizer.sanitize_message(msg)
        assert result["content"] == "abc"

    def test_sanitize_removes_surrogates(self):
        msg = {"role": "user", "content": "hi\ud800there"}
        result = MessageSanitizer.sanitize_message(msg)
        assert result["content"] == "hithere"

    def test_sanitize_list_content(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "image_url", "image_url": {"url": "data:..."}, "vision_enabled": True},
            ],
        }
        result = MessageSanitizer.sanitize_message(msg)
        assert len(result["content"]) == 2

    def test_sanitize_list_removes_disabled_images(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "image_url", "image_url": {"url": "data:..."}, "vision_enabled": False},
            ],
        }
        result = MessageSanitizer.sanitize_message(msg)
        assert len(result["content"]) == 1

    def test_sanitize_messages_batch(self):
        msgs = [
            {"role": "user", "content": "a\r\nb"},
            {"role": "assistant", "content": "c\x00d"},
        ]
        result = MessageSanitizer.sanitize_messages(msgs)
        assert result[0]["content"] == "a\nb"
        assert result[1]["content"] == "cd"
