import pytest
import requests

import weather_provider as wp_module
import web_search as ws_module
from conftest import FakeResponse

GEO = {
    "results": [
        {"name": "London", "latitude": 51.5, "longitude": -0.12, "country": "United Kingdom",
         "admin1": "England", "country_code": "GB"},
        {"name": "London", "latitude": 42.98, "longitude": -81.24, "country": "Canada",
         "admin1": "Ontario", "country_code": "CA"},
    ]
}
FORECAST = {
    "current": {"time": "2026-09-29T14:00", "temperature_2m": 18.2, "relative_humidity_2m": 60,
                "weather_code": 3, "wind_speed_10m": 12.0},
    "daily": {"time": ["2026-09-29", "2026-09-30"], "temperature_2m_max": [20, 22],
              "temperature_2m_min": [10, 11], "weather_code": [3, 61], "precipitation_sum": [0, 4.2]},
}


@pytest.fixture
def fake_get(monkeypatch):
    calls = []

    def fake(url, params=None, timeout=None):
        calls.append((url, params))
        if "geocoding" in url:
            if params["name"] == "Nowhereville":
                return FakeResponse({})
            return FakeResponse(GEO)
        if params["latitude"] == 0:
            return FakeResponse({"error": True}, status=500)
        return FakeResponse(FORECAST)

    monkeypatch.setattr(wp_module.requests, "get", fake)
    return calls


def test_find_place_and_qualifiers(fake_get):
    wp = wp_module.WeatherProvider()
    assert wp.find_place("London")["label"] == "London, England, United Kingdom"
    assert wp.find_place("London, Ontario")["label"] == "London, Ontario, Canada"
    assert wp.find_place("London, CA")["latitude"] == 42.98
    assert wp.find_place("London, United Kingdom")["latitude"] == 51.5
    assert wp.find_place("London, Mars") is None
    assert wp.find_place("Nowhereville") is None
    assert wp.find_place(" , x") is None
    assert wp.get_coordinates("London") == (51.5, -0.12)
    assert fake_get[1][1]["count"] == 10  # qualified lookups ask for several matches


def test_get_weather_report(fake_get):
    report = wp_module.WeatherProvider().get_weather("London, Ontario")
    assert "London, Ontario, Canada" in report
    assert "local time 2026-09-29 14:00" in report
    assert "Temperature: 18.2°C" in report and "Overcast" in report
    assert "Slight rain" in report and "Precipitation: 4.2mm" in report


def test_get_weather_tomorrow(fake_get):
    report = wp_module.WeatherProvider().get_weather_for_tomorrow("London")
    assert report.startswith("🌤️ Weather Tomorrow (Wed, Sep 30) in London, England")
    assert "11°C to 22°C" in report and "Precipitation: 4.2mm" in report


def test_weather_not_found_and_api_errors(fake_get, monkeypatch):
    wp = wp_module.WeatherProvider()
    assert wp.get_weather("Nowhereville") == "❌ Could not find location: Nowhereville"
    assert wp.get_weather_for_tomorrow("Nowhereville").startswith("❌ Could not find")
    monkeypatch.setattr(wp, "find_place", lambda name: {"latitude": 0, "longitude": 0, "label": "Zero"})
    assert wp.get_weather("x").startswith("❌ Weather error")
    assert wp.get_weather_for_tomorrow("x").startswith("❌ Weather error")


def test_geocoding_network_error(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("offline")
    monkeypatch.setattr(wp_module.requests, "get", boom)
    assert wp_module.WeatherProvider().get_weather("London") == "❌ Could not find location: London"


def test_weather_codes():
    wp = wp_module.WeatherProvider()
    assert wp._get_weather_condition(0) == "Clear sky"
    assert wp._get_weather_condition(42) == "Unknown (code 42)"


# ---------------- Web search

class FakeDDGS:
    hits = [{"title": "Result one", "body": "First snippet", "href": "https://one.example"},
            {"title": "Result two", "body": "x" * 500, "href": "https://two.example"}]
    error = None

    def __init__(self, timeout=None):
        pass

    def text(self, query, max_results=5):
        if FakeDDGS.error:
            raise FakeDDGS.error
        return FakeDDGS.hits[:max_results]


@pytest.fixture
def web(monkeypatch):
    import sys
    import types
    FakeDDGS.hits = list(FakeDDGS.__dict__["hits"])
    FakeDDGS.error = None
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    answers = {"instant": {"AbstractText": "An abstract.", "Answer": "42"},
               "wiki": {"query": {"search": [{"title": "Some Page", "snippet": "a <span class=\"searchmatch\">match</span>"}]}}}

    def fake_get(url, params=None, timeout=None, headers=None):
        if "wikipedia" in url:
            assert "PersonalAIAssistant" in headers["User-Agent"]
            return FakeResponse(answers["wiki"])
        return FakeResponse(answers["instant"])

    monkeypatch.setattr(ws_module.requests, "get", fake_get)
    return answers


def test_search_combines_instant_answer_and_web_results(web):
    text = ws_module.WebSearcher().search("question", num_results=2)
    lines = text.splitlines()
    assert lines[0] == "🔍 Search results for 'question':"
    assert lines[1:3] == ["📌 42", "📌 An abstract."]
    assert lines[3] == "- Result one: First snippet (https://one.example)"
    assert len(lines[4]) < 400  # long snippets are shortened


def test_search_falls_back_to_wikipedia(web):
    FakeDDGS.hits = []
    web["instant"] = {}
    text = ws_module.WebSearcher().search("question")
    assert "- Some Page: a match (https://en.wikipedia.org/wiki/Some_Page)" in text


def test_search_survives_every_source_failing(web, monkeypatch):
    FakeDDGS.error = RuntimeError("rate limited")

    def offline(*a, **k):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(ws_module.requests, "get", offline)
    assert ws_module.WebSearcher().search("question") == "No results found"


def test_search_without_ddgs_installed(web, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "ddgs", None)  # import fails
    assert "Some Page" in ws_module.WebSearcher().search("question")
