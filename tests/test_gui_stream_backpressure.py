import threading
import time


def test_stream_queue_is_bounded_and_releases_blocked_producer_on_cancel():
    from gui.api import _CancellableStreamQueue

    stopped = threading.Event()
    stream_queue = _CancellableStreamQueue(stopped, maxsize=1)
    assert stream_queue.put(("chunk", "first")) is True

    result = {}

    def producer():
        result["accepted"] = stream_queue.put(("chunk", "second"))

    thread = threading.Thread(target=producer)
    thread.start()
    time.sleep(0.05)
    assert thread.is_alive()

    stopped.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert result["accepted"] is False
