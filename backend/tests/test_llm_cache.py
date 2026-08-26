"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json

import pytest

from app import llm_cache

MODEL = "gemini-3.6-flash"
OTHER_MODEL = "gemini-3.7-flash"


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    """Point the cache at a throwaway file and reset in-process state."""
    path = tmp_path / "llm_cache.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(llm_cache, "CACHE_PATH", str(path))
    llm_cache._STORE = None
    llm_cache.reset_stats()
    return path


def test_key_is_stable_across_dict_ordering(temp_cache):
    a = llm_cache.cache_key(MODEL, 1, {"x": 1, "y": 2})
    b = llm_cache.cache_key(MODEL, 1, {"y": 2, "x": 1})
    assert a == b


def test_key_changes_with_prompt_version(temp_cache):
    a = llm_cache.cache_key(MODEL, 1, {"x": 1})
    b = llm_cache.cache_key(MODEL, 2, {"x": 1})
    assert a != b


def test_key_changes_with_model(temp_cache):
    """A recorded answer belongs to the model that produced it."""
    a = llm_cache.cache_key(MODEL, 1, {"x": 1})
    b = llm_cache.cache_key(OTHER_MODEL, 1, {"x": 1})
    assert a != b


def test_hit_returns_recorded_response(temp_cache, monkeypatch):
    monkeypatch.setattr(llm_cache, "DEMO_MODE", True)
    key = llm_cache.cache_key(MODEL, 1, {"q": "why"})
    temp_cache.write_text(json.dumps({
        key: {
            "model": MODEL,
            "text": '{"answer": 42}',
            "input_tokens": 120,
            "output_tokens": 18,
            "latency_ms": 431,
            "recorded_at": "2026-08-25T00:00:00Z",
            "inputs": {"q": "why"},
        }
    }), encoding="utf-8")
    llm_cache._STORE = None

    response = llm_cache.call(
        model=MODEL, prompt_version=1,
        inputs={"q": "why"}, contents="ignored on a hit",
    )

    assert response.text == '{"answer": 42}'
    assert response.latency_ms == 431
    assert response.cached is True
    assert llm_cache.stats()["hits"] == 1


def test_miss_in_demo_mode_raises_rather_than_falling_back(temp_cache, monkeypatch):
    monkeypatch.setattr(llm_cache, "DEMO_MODE", True)

    with pytest.raises(llm_cache.CacheMiss) as excinfo:
        llm_cache.call(
            model=MODEL, prompt_version=1,
            inputs={"q": "unrecorded"}, contents="prompt",
        )

    assert "refresh-llm-cache" in str(excinfo.value)
    assert llm_cache.stats()["misses"] == 1


def test_replayed_latency_is_identical_across_calls(temp_cache, monkeypatch):
    """The value entering the hash preimage must not drift between runs."""
    monkeypatch.setattr(llm_cache, "DEMO_MODE", True)
    key = llm_cache.cache_key(MODEL, 1, {"q": "why"})
    temp_cache.write_text(json.dumps({
        key: {
            "model": MODEL, "text": "ok",
            "input_tokens": 1, "output_tokens": 1, "latency_ms": 999,
            "recorded_at": "2026-08-25T00:00:00Z", "inputs": {"q": "why"},
        }
    }), encoding="utf-8")
    llm_cache._STORE = None

    first = llm_cache.call(model=MODEL, prompt_version=1,
                           inputs={"q": "why"}, contents="p")
    second = llm_cache.call(model=MODEL, prompt_version=1,
                            inputs={"q": "why"}, contents="p")

    assert first.latency_ms == second.latency_ms == 999
