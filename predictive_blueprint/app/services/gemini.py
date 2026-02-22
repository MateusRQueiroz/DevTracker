import os
import json
import re
from google import genai


DEFAULT_MARKS = {
    "complexity_score": 4,
    "estimated_features_count": 4,
    "tech_difficulty": 4,
    "integration_complexity": 4,
    "uncertainty_factor": 4,
}


def clean_json_response(text: str) -> str:
    text = text.strip()

    # Remove markdown fences if present
    text = re.sub(r"^```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)

    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def get_complexity_marks(
    title: str,
    description: str,
    tech_stack: list[str],
) -> dict:

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("Gemini error: API key not found")
            return DEFAULT_MARKS

        client = genai.Client(api_key=api_key)

        prompt = f"""
You are a senior software architect.

Analyze the following project and return ONLY valid JSON.

Return this exact schema:

{{
  "complexity_score": int (1-10),
  "estimated_features_count": int (1-10),
  "tech_difficulty": int (1-10),
  "integration_complexity": int (1-10),
  "uncertainty_factor": int (1-10)
}}

Project Title:
{title}

Project Description:
{description}

Tech Stack:
{", ".join(tech_stack)}
"""

        # NOTE: Gemini 1.5 model IDs may be deprecated/shutdown for many API keys.
        # Allow overriding via env var without changing code.
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )

        raw_text = response.text
        cleaned = clean_json_response(raw_text)
        parsed = json.loads(cleaned)

        return parsed

    except Exception as e:
        print("Gemini error:", e)
        return DEFAULT_MARKS