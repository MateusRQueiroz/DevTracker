from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import requests


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash").strip()


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """
    Gemini sometimes wraps JSON in text. Grab the first {...} block.
    """
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def get_complexity(*, title: str, description: str, tech_stack: list[str]) -> int:
    """
    Returns an integer 1..5.
    If Gemini not configured or fails, returns 3.
    """
    if not GEMINI_API_KEY:
        return 3  

    prompt = f"""
You are a strict scoring function.
Given a software project, return ONLY valid JSON like:
{{"complexity": 1, "reason": "..." }}

Rules:
- complexity must be an integer 1..5
- 1 = tiny CRUD/landing page
- 3 = normal full-stack app
- 5 = complex integrations, heavy infra, hard constraints

Project:
Title: {title}
Description: {description}
Tech Stack: {tech_stack}
""".strip()

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }

    try:
        resp = requests.post(url, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        parsed = _extract_json(text)
        if not parsed:
            return 3

        c = int(parsed.get("complexity", 3))
        if c < 1:
            return 1
        if c > 5:
            return 5
        return c
    except Exception:
        return 3