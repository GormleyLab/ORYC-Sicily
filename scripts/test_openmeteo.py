"""Unit tests for the Open-Meteo HTTP layer.

These exist because of a real incident: on 2026-09-23 the 05:40 run died on a
bare `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. Open-Meteo
had answered HTTP 200 with a body that was not JSON, `r.json()` raised, and
that message - naming no URL, no status, no body - is what the page printed to
the fleet under "Forecast is stale". Every error out of `_get` must now say
which URL failed and why, and the transient shapes must be retried.

Run: python -m pytest scripts/ -q
"""

import pytest
import requests

import openmeteo as om


class FakeResponse:
    def __init__(self, status_code=200, text="", ctype="application/json", payload=None):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": ctype}
        self._payload = payload

    @property
    def content(self):
        return self.text.encode()

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Keep the retry backoff from making the suite slow."""
    monkeypatch.setattr(om.time, "sleep", lambda _: None)


def _responses(monkeypatch, *responses):
    """Serve the given responses in order; record how many calls were made."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        r = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(om.requests, "get", fake_get)
    return calls


# --- The incident -----------------------------------------------------------

def test_html_body_with_http_200_is_reported_not_raw_decoder_error(monkeypatch):
    """A 200 carrying HTML must name the URL, the content type and the body."""
    page = "<html><head><title>502 Bad Gateway</title></head></html>"
    _responses(monkeypatch, FakeResponse(text=page, ctype="text/html"))

    with pytest.raises(om.OpenMeteoError) as e:
        om._get("https://api.open-meteo.com/v1/forecast", {"latitude": 38.5})

    msg = str(e.value)
    assert "api.open-meteo.com/v1/forecast" in msg     # which call failed
    assert "not JSON" in msg
    assert "text/html" in msg                          # what came back instead
    assert "502 Bad Gateway" in msg                    # and its first bytes
    assert "Expecting value" not in msg                # never the bare decoder error


def test_non_json_200_is_retried_and_recovers(monkeypatch):
    """The 2026-09-23 outage cleared in minutes; one retry would have saved it."""
    good = {"hourly": {"time": []}}
    calls = _responses(
        monkeypatch,
        FakeResponse(text="", ctype="text/html"),
        FakeResponse(payload=good),
    )

    assert om._get("https://api.open-meteo.com/v1/forecast") == good
    assert len(calls) == 2


def test_an_empty_body_is_also_caught(monkeypatch):
    """Zero bytes with a JSON content-type decodes no better than HTML does."""
    _responses(monkeypatch, FakeResponse(text=""))

    with pytest.raises(om.OpenMeteoError) as e:
        om._get("https://api.open-meteo.com/v1/forecast")
    assert "0 bytes" in str(e.value)


# --- Retry policy -----------------------------------------------------------

def test_client_errors_are_not_retried(monkeypatch):
    """A malformed request will fail identically however many times we ask."""
    calls = _responses(monkeypatch, FakeResponse(status_code=400, text="bad parameter"))

    with pytest.raises(om.OpenMeteoError) as e:
        om._get("https://api.open-meteo.com/v1/forecast")
    assert len(calls) == 1
    assert "HTTP 400" in str(e.value)
    assert "bad parameter" in str(e.value)


def test_rate_limiting_is_retried(monkeypatch):
    """429 is the one 4xx worth waiting out - the free tier is shared."""
    good = {"hourly": {"time": []}}
    calls = _responses(
        monkeypatch,
        FakeResponse(status_code=429, text="Too many requests"),
        FakeResponse(payload=good),
    )

    assert om._get("https://api.open-meteo.com/v1/forecast") == good
    assert len(calls) == 2


def test_server_errors_are_retried_then_give_up(monkeypatch):
    calls = _responses(monkeypatch, FakeResponse(status_code=503, text="unavailable"))

    with pytest.raises(om.OpenMeteoError) as e:
        om._get("https://api.open-meteo.com/v1/forecast")
    assert len(calls) == om.RETRIES
    assert "HTTP 503" in str(e.value)


def test_connection_errors_are_retried_and_named(monkeypatch):
    calls = _responses(monkeypatch, requests.ConnectionError("name resolution failed"))

    with pytest.raises(om.OpenMeteoError) as e:
        om._get("https://marine-api.open-meteo.com/v1/marine")
    assert len(calls) == om.RETRIES
    assert "marine-api.open-meteo.com" in str(e.value)
    assert "name resolution failed" in str(e.value)
