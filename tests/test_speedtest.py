import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import speedtest
from speedtest import Attempt, Summary, measure, with_cache_buster

PAYLOAD = b"x" * 200_000


class PayloadHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — имя задаёт http.server
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, *args):  # тишина в выводе тестов
        pass


@pytest.fixture
def local_url():
    server = HTTPServer(("127.0.0.1", 0), PayloadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/image.jpg"
    finally:
        server.shutdown()


def test_summary_math():
    summary = Summary((Attempt(1.0, 1_000_000), Attempt(3.0, 3_000_000)))
    assert summary.total_bytes == 4_000_000
    assert summary.total_seconds == 4.0
    assert summary.average_seconds == 2.0
    assert summary.megabytes_per_second == pytest.approx(1.0)
    assert summary.megabits_per_second == pytest.approx(8.0)


def test_cache_buster_keeps_existing_query():
    url = with_cache_buster("https://example.com/img.jpg?size=big", "42")
    assert url == "https://example.com/img.jpg?size=big&_speedtest=42"


def test_measure_runs_sequential_requests(local_url):
    seen = []
    summary = measure(local_url, runs=3, timeout=5, on_attempt=lambda i, a: seen.append(i))

    assert seen == [1, 2, 3]
    assert [a.size for a in summary.attempts] == [len(PAYLOAD)] * 3
    assert summary.total_bytes == 3 * len(PAYLOAD)
    assert summary.total_seconds > 0
    assert summary.megabytes_per_second > 0


def test_measure_rejects_zero_runs(local_url):
    with pytest.raises(ValueError):
        measure(local_url, runs=0, timeout=5)


def test_main_returns_error_code_for_unreachable_host(capsys):
    code = speedtest.main(["http://127.0.0.1:9/never", "--runs", "1", "--timeout", "0.5"])
    assert code == 1
    assert "не удалось скачать" in capsys.readouterr().err
