from __future__ import annotations

import os
import re
import requests


def get_complexity(*, title: str, description: str, tech_stack: list[str]) -> int:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest").strip()

    # allow either "models/xxx" or "xxx"
    if model.startswith("models/"):
        model = model[len("models/"):]

    if not api_key:
        return 2  # safe default if key missing

    prompt = (
        "You are a project estimator. "
        "Return ONLY ONE DIGIT from 1 to 5.\n\n"
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Tech stack: {', '.join(tech_stack)}\n\n"
        "Output format: just a single digit 1-5."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 5},
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

        m = re.search(r"^([1-5])$", text)
        if not m:
            return 3
        return int(m.group(1))

    except Exception as e:
        print("Gemini error:", repr(e))
        return 3