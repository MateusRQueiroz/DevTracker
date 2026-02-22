from __future__ import annotations

import json
import os
from typing import Any

import requests


DEFAULT_MARKS: dict[str, int] = {
    "complexity_score": 4,
    "estimated_features_count": 4,
    "tech_difficulty": 4,
    "integration_complexity": 4,
    "uncertainty_factor": 4,
}


def _clamp_1_10(x: Any, default: int = 4) -> int:
    try:
        v = int(x)
    except Exception:
        return default
    return max(1, min(10, v))


def get_project_marks(*, title: str, description: str, tech_stack: list[str]) -> dict[str, int]:
    """Return 5 marks, each 1..10, from Gemini.

    If GEMINI_API_KEY is missing or Gemini fails, returns safe defaults.
    """

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest").strip()

    # allow either "models/xxx" or "xxx"
    if model.startswith("models/"):
        model = model[len("models/"):]

    if not api_key:
        return dict(DEFAULT_MARKS)

    prompt = (
        "You are a project estimation assistant. "
        "Given the project inputs, output ONLY valid JSON with these integer keys (1-10): "
        "complexity_score, estimated_features_count, tech_difficulty, integration_complexity, uncertainty_factor. "
        "No markdown, no explanations, no extra keys.\n\n"
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Tech stack: {', '.join(tech_stack)}\n"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 120,
        },
    }

    try:
        resp = requests.post(url, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )

        parsed = json.loads(text)
        return {
            "complexity_score": _clamp_1_10(parsed.get("complexity_score"), DEFAULT_MARKS["complexity_score"]),
            "estimated_features_count": _clamp_1_10(
                parsed.get("estimated_features_count"),
                DEFAULT_MARKS["estimated_features_count"],
            ),
            "tech_difficulty": _clamp_1_10(parsed.get("tech_difficulty"), DEFAULT_MARKS["tech_difficulty"]),
            "integration_complexity": _clamp_1_10(
                parsed.get("integration_complexity"),
                DEFAULT_MARKS["integration_complexity"],
            ),
            "uncertainty_factor": _clamp_1_10(parsed.get("uncertainty_factor"), DEFAULT_MARKS["uncertainty_factor"]),
        }

    except Exception as e:
        print("Gemini error:", repr(e))
        return dict(DEFAULT_MARKS)
