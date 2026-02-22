from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from google import genai


# Conservative fallback if Gemini fails.
# (We still prefer the heuristic fallback below over a fixed constant 4.)
DEFAULT_MARKS: dict[str, int] = {
    "complexity_score": 4,
    "estimated_features_count": 4,
    "tech_difficulty": 4,
    "integration_complexity": 4,
    "uncertainty_factor": 4,
}


def _clamp_1_10(x: Any, default: int = 4) -> int:
    try:
        v = int(float(x))
    except Exception:
        v = default
    return max(1, min(10, v))


def clean_json_response(text: str) -> str:
    text = (text or "").strip()

    # Remove markdown fences if present
    text = re.sub(r"^```json", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^```", "", text).strip()
    text = re.sub(r"```$", "", text).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _heuristic_marks(title: str, description: str, tech_stack: list[str]) -> dict[str, int]:
    """Deterministic local fallback when Gemini is unavailable.

    Goal: never silently return the same constant marks (4,4,4,4,4) for every project.
    This keeps the app usable offline / when keys are missing, and makes failures obvious.
    """

    t = (title or "").strip().lower()
    d = (description or "").strip().lower()
    stack = [str(x).strip().lower() for x in (tech_stack or []) if str(x).strip()]
    stack_set = set(stack)

    # Signal from text length (rough)
    text_len = len((title or "") + " " + (description or ""))
    if text_len >= 1200:
        length_score = 8
    elif text_len >= 800:
        length_score = 7
    elif text_len >= 500:
        length_score = 6
    elif text_len >= 250:
        length_score = 5
    elif text_len >= 120:
        length_score = 4
    elif text_len >= 60:
        length_score = 3
    else:
        length_score = 2

    # Signal from stack breadth
    stack_score = min(10, max(1, 2 + len(stack_set)))

    # Keyword-driven complexity bumps
    bump = 0
    keywords = [
        "auth",
        "login",
        "payments",
        "stripe",
        "webhook",
        "realtime",
        "websocket",
        "stream",
        "multi-tenant",
        "rbac",
        "permissions",
        "scrape",
        "crawler",
        "ml",
        "model",
        "forecast",
        "recommendation",
        "kafka",
        "queue",
        "celery",
        "microservice",
        "event-driven",
        "kubernetes",
        "k8s",
        "terraform",
    ]
    hay = f"{t} {d} " + " ".join(stack)
    for kw in keywords:
        if kw in hay:
            bump += 1

    complexity = _clamp_1_10(round(0.55 * length_score + 0.45 * stack_score + 0.35 * bump), default=4)

    # Features: lean more on stack breadth and explicit list-y descriptions
    features = _clamp_1_10(round(0.50 * stack_score + 0.40 * bump + (1 if "dashboard" in hay else 0)), default=4)

    # Tech difficulty: infra/tools bump it
    infra = any(k in stack_set for k in ["aws", "gcp", "azure", "docker", "k8s", "kubernetes", "terraform"])
    tech_difficulty = _clamp_1_10(round(0.55 * stack_score + 0.35 * bump + (2 if infra else 0)), default=4)

    # Integration: APIs and multiple systems
    integration = _clamp_1_10(round(0.45 * stack_score + 0.45 * bump + (1 if "api" in hay else 0)), default=4)

    # Uncertainty: vague descriptions + new stacks
    vague = any(k in hay for k in ["tbd", "unknown", "not sure", "figure out", "maybe", "research"])
    uncertainty = _clamp_1_10(round(3 + (2 if vague else 0) + 0.25 * bump + (1 if infra else 0)), default=4)

    return {
        "complexity_score": complexity,
        "estimated_features_count": features,
        "tech_difficulty": tech_difficulty,
        "integration_complexity": integration,
        "uncertainty_factor": uncertainty,
    }


def get_complexity_marks(
    title: str,
    description: str,
    tech_stack: list[str],
) -> Dict[str, int]:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()

    # Accept either "models/xxx" or "xxx"
    model = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    if model.startswith("models/"):
        model = model[len("models/") :]

    # If key missing, use heuristic (and surface that to caller)
    if not api_key:
        data = _heuristic_marks(title, description, tech_stack)
        data["gemini_ok"] = False
        data["gemini_error"] = "Missing API key"
        return data
    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""
You are a senior software architect.

Analyze the following project and return STRICT JSON ONLY.

Rate each dimension from 1–10 (integers).

Fields required:
- complexity_score
- estimated_features_count
- tech_difficulty
- integration_complexity
- uncertainty_factor

Title: {title}
Description: {description}
Tech stack: {', '.join(tech_stack)}

Return ONLY valid JSON.
""".strip()

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )

        raw_text = getattr(response, "text", "") or ""
        cleaned = clean_json_response(raw_text)
        data = json.loads(cleaned)

        out: dict[str, int] = {}
        for key, default in DEFAULT_MARKS.items():
            out[key] = _clamp_1_10(data.get(key, default), default=default)

        out["gemini_ok"] = True
        out["gemini_error"] = None
        return out

    except Exception as e:
        # Never silently return all-4s; use deterministic local heuristic fallback.
        data = _heuristic_marks(title, description, tech_stack)
        data["gemini_ok"] = False
        data["gemini_error"] = str(e)
        return data
