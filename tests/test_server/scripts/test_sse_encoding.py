from apps.api import _sse_data


def test_multiline_sse_content_prefixes_every_line():
    encoded = _sse_data("summary\n- first\n- second")

    assert encoded == "data: summary\ndata: - first\ndata: - second\n\n"
