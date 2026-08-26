"""
RecoverOS LLM Cache

Every Gemini call in this system goes through here.

The problem this solves: the ledger hashes LLM metadata (model, latency,
confidence) and the response text lands in the hashed `details` field. A live
model call returns different text and a different latency on every run, so a
demo that called Gemini directly could never reproduce its own chain head - and
reproducibility is the claim the whole project rests on.

So responses are recorded once against a real API key and committed to
`backend/data/llm_cache.json`. Demo mode replays them. The recorded file is
also the evidence: a reviewer with no API key can read exactly what the model
returned.

A cache miss in demo mode raises. It does NOT fall back to a template. A silent
fallback is precisely what made the previous build's AI claims unverifiable -
the demo looked identical whether the model ran or not.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.config import DEMO_MODE, GEMINI_API_KEY

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "llm_cache.json",
)

_STORE: Optional[dict] = None
_STATS = {"hits": 0, "misses": 0, "writes": 0}


class CacheMiss(RuntimeError):
    """Raised when demo mode needs a response that was never recorded."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cached: bool


def load(path: Optional[str] = None) -> dict:
    global _STORE
    if _STORE is None:
        target = path or CACHE_PATH
        try:
            with open(target, "r", encoding="utf-8") as handle:
                _STORE = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            _STORE = {}
    return _STORE


def save(path: Optional[str] = None) -> None:
    target = path or CACHE_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(load(), handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def cache_key(model: str, prompt_version: int, inputs: dict) -> str:
    """
    Identity of a call.

    `prompt_version` is part of the key on purpose: editing prompt text without
    bumping it would silently replay a response to a question no longer being
    asked.
    """
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    material = f"{model}|{prompt_version}|{canonical}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def stats() -> dict:
    return dict(_STATS)


def reset_stats() -> None:
    for key in _STATS:
        _STATS[key] = 0


def call(
    *,
    model: str,
    prompt_version: int,
    inputs: dict,
    contents: str,
    response_mime_type: Optional[str] = None,
) -> LLMResponse:
    store = load()
    key = cache_key(model, prompt_version, inputs)

    hit = store.get(key)
    if hit is not None:
        _STATS["hits"] += 1
        return LLMResponse(
            text=hit["text"],
            model=hit["model"],
            input_tokens=hit["input_tokens"],
            output_tokens=hit["output_tokens"],
            latency_ms=hit["latency_ms"],
            cached=True,
        )

    _STATS["misses"] += 1

    if DEMO_MODE:
        raise CacheMiss(
            f"No recorded Gemini response for key {key[:12]}... "
            f"(model={model}, prompt_version={prompt_version}). "
            f"Demo mode replays recorded responses and never invents one. "
            f"Run `make refresh-llm-cache` with a valid GEMINI_API_KEY."
        )

    if not GEMINI_API_KEY or "XXXX" in GEMINI_API_KEY:
        raise CacheMiss(
            "Live mode requested but GEMINI_API_KEY is unset or a placeholder."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.GenerateContentConfig(response_mime_type=response_mime_type) \
        if response_mime_type else None

    started = time.time()
    response = client.models.generate_content(
        model=model, contents=contents, config=config,
    )
    latency_ms = int((time.time() - started) * 1000)

    usage = getattr(response, "usage_metadata", None)
    record = {
        "model": model,
        "text": (response.text or "").strip(),
        "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
        "latency_ms": latency_ms,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
    }
    store[key] = record
    _STATS["writes"] += 1
    save()

    return LLMResponse(
        text=record["text"], model=model,
        input_tokens=record["input_tokens"],
        output_tokens=record["output_tokens"],
        latency_ms=latency_ms, cached=False,
    )
