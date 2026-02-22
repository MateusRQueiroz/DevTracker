from __future__ import annotations

import json
import math
import os
import re
from datetime import date, timedelta
from typing import Iterable

from google import genai

from app.models import Dev, Project

# ------------------------------
# Calibration knobs (easy to tune)
# ------------------------------

HOURS_PER_DEV_PER_DAY = 6.0

# "Hours per point" for Gemini marks (1..10)
# Each category is linear: score=2 means 2x the base.
HOURS_PER_POINT = {
    "complexity_score": 18.0,
    "estimated_features_count": 14.0,
    "tech_difficulty": 20.0,
    "integration_complexity": 12.0,
    "uncertainty_factor": 8.0,
}

SENIORITY_MULT = {
    "JUNIOR": 0.8,
    "MID": 1.0,
    "SENIOR": 1.2,
}


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def count_weekdays(start: date, end: date) -> int:
    """Count weekdays from start to end inclusive. If end < start, returns 0."""
    if end < start:
        return 0
    days = 0
    cur = start
    while cur <= end:
        if _is_weekday(cur):
            days += 1
        cur += timedelta(days=1)
    return days


def add_workdays(start: date, workdays: int) -> date:
    """Add N weekdays to start (start is day 0). workdays=0 returns start."""
    if workdays <= 0:
        return start
    cur = start
    added = 0
    while added < workdays:
        cur += timedelta(days=1)
        if _is_weekday(cur):
            added += 1
    return cur


def required_roles_from_stack(tech_stack: Iterable[str]) -> set[str]:
    s = {x.strip().lower() for x in tech_stack if isinstance(x, str)}
    req: set[str] = set()

    if any(k in s for k in ["react", "vue", "angular", "frontend", "nextjs", "next.js", "ui"]):
        req.add("FE")

    if any(k in s for k in ["django", "flask", "fastapi", "backend", "node", "express", "api"]):
        req.add("BE")

    # DevOps ONLY when infra is explicitly selected
    if _has_devops_stack(tech_stack) or ("devops" in s):
        req.add("DEVOPS")

    if not req:
        req.add("BE")
    return req



def _has_devops_stack(tech_stack: Iterable[str]) -> bool:
    s = {x.strip().lower() for x in tech_stack if isinstance(x, str)}
    return any(k in s for k in ["aws", "gcp", "azure", "docker", "k8s", "kubernetes", "terraform"])

def _has_light_devops_work(tech_stack: Iterable[str]) -> bool:
    """True if the project likely needs some build/deploy/config work even without infra keywords."""
    s = {x.strip().lower() for x in tech_stack if isinstance(x, str)}
    return any(k in s for k in ["django", "flask", "fastapi", "node", "express", "react", "vue", "angular"])





def compute_capacity_hours_by_role(devs: list[Dev], working_days_until_deadline: int) -> dict[str, float]:
    cap: dict[str, float] = {"FE": 0.0, "BE": 0.0, "DEVOPS": 0.0}
    for d in devs:
        mult = SENIORITY_MULT.get(d.seniority, 1.0)
        cap[d.role] = cap.get(d.role, 0.0) + (working_days_until_deadline * HOURS_PER_DEV_PER_DAY * mult)
    return cap


def compute_effort_hours(
    *,
    complexity_score: int,
    estimated_features_count: int,
    tech_difficulty: int,
    integration_complexity: int,
    uncertainty_factor: int,
) -> float:
    return float(
        complexity_score * HOURS_PER_POINT["complexity_score"]
        + estimated_features_count * HOURS_PER_POINT["estimated_features_count"]
        + tech_difficulty * HOURS_PER_POINT["tech_difficulty"]
        + integration_complexity * HOURS_PER_POINT["integration_complexity"]
        + uncertainty_factor * HOURS_PER_POINT["uncertainty_factor"]
    )


def compute_adjusted_effort_score(
    *,
    complexity_score: int,
    estimated_features_count: int,
    tech_difficulty: int,
    integration_complexity: int,
    uncertainty_factor: int,
) -> int:
    # Weighted average + a small risk uplift.
    base = (
        0.25 * complexity_score
        + 0.20 * estimated_features_count
        + 0.30 * tech_difficulty
        + 0.25 * integration_complexity
    )
    uplift = 1.0 + (max(1, min(10, uncertainty_factor)) - 1) * 0.03
    score = int(round(base * uplift))
    return max(1, min(10, score))


def _extract_json_object(text: str) -> str:
    """Extract first {...} JSON object from model output."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _normalize_split(split: dict[str, float]) -> dict[str, float]:
    fe = _clamp01(split.get("FE", 0.0))
    be = _clamp01(split.get("BE", 0.0))
    devops = _clamp01(split.get("DEVOPS", 0.0))
    total = fe + be + devops
    if total <= 0.0:
        return {"FE": 0.0, "BE": 1.0, "DEVOPS": 0.0}
    return {"FE": fe / total, "BE": be / total, "DEVOPS": devops / total}


def _gemini_role_split(
    *,
    required_roles: set[str],
    tech_stack: Iterable[str],
    estimated_features_count: int,
    tech_difficulty: int,
    integration_complexity: int,
) -> dict[str, float] | None:
    """Ask Gemini for a FE/BE/DEVOPS fraction split that sums to 1.0.

    Returns None on any failure so caller can fallback.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest").strip()
    if model.startswith("models/"):
        model = model[len("models/") :]

    ef = max(1, min(10, int(estimated_features_count)))
    td = max(1, min(10, int(tech_difficulty)))
    ic = max(1, min(10, int(integration_complexity)))

    stack_list = [str(x).strip() for x in tech_stack if isinstance(x, str) and str(x).strip()]
    req_list = sorted(required_roles)

    prompt = f"""
You are a software delivery estimator.

Task:
Given the project's required roles and tech stack plus 3 difficulty marks, output the labor split fractions
for FE, BE, and DEVOPS.

Rules:
- Output MUST be valid JSON ONLY (no markdown, no commentary).
- Keys must be exactly: "FE", "BE", "DEVOPS"
- Values must be numbers between 0 and 1 (floats are fine).
- The three values must sum to 1.0 (within rounding).
- If a role is not required (not in required_roles), set it to 0 unless the stack truly implies it.
- Allocate DEVOPS for true infra work when infra keywords are present.
- Even without infra keywords, allocate a small DEVOPS slice (typically 0.05-0.12) for build/deploy/config/CI unless this is clearly a tiny throwaway script.

Inputs:
required_roles={req_list}
tech_stack={stack_list}
estimated_features_count={ef}  (1..10)
tech_difficulty={td}           (1..10)
integration_complexity={ic}    (1..10)

Output JSON example:
{{"FE": 0.35, "BE": 0.55, "DEVOPS": 0.10}}
""".strip()

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        raw = getattr(resp, "text", None) or ""
        data = json.loads(_extract_json_object(raw))

        split = {
            "FE": float(data.get("FE", data.get("fe", 0.0)) or 0.0),
            "BE": float(data.get("BE", data.get("be", 0.0)) or 0.0),
            "DEVOPS": float(data.get("DEVOPS", data.get("devops", 0.0)) or 0.0),
        }
        return _normalize_split(split)
    except Exception:
        return None


def compute_role_split_fractions(
    *,
    required_roles: set[str],
    tech_stack: Iterable[str],
    estimated_features_count: int,
    tech_difficulty: int,
    integration_complexity: int,
) -> dict[str, float]:
    """Return role fractions that sum to 1.

    Practical goals:
    - Avoid unrealistic *zero frontend* when the project is clearly a web app.
    - Avoid unrealistic *zero DevOps*: even without explicit infra, most web apps need some deploy/config/CI.
      Keep DevOps small unless infra keywords are present.

    This stays deterministic and stable even if Gemini output is noisy.
    """
    infra = _has_devops_stack(tech_stack)
    light_devops = _has_light_devops_work(tech_stack)

    # DevOps is always allowed at least as a small slice for web apps.
    devops_allowed = infra or light_devops or ("DEVOPS" in required_roles)

    ef = max(1, min(10, int(estimated_features_count)))
    td = max(1, min(10, int(tech_difficulty)))
    ic = max(1, min(10, int(integration_complexity)))

    s = {x.strip().lower() for x in tech_stack if isinstance(x, str)}
    explicit_fe = any(k in s for k in ["react", "vue", "angular", "nextjs", "next.js", "frontend", "ui"])

    # Minimum FE fraction if FE is required.
    min_fe = 0.0
    if "FE" in required_roles:
        min_fe = 0.35 if explicit_fe else 0.25

    # Minimum DevOps fraction (baseline deploy/config), larger when infra exists or complexity is higher.
    min_devops = 0.0
    if devops_allowed:
        if infra:
            min_devops = 0.10
        else:
            min_devops = 0.06
            if ic >= 7 or td >= 7 or ef >= 7:
                min_devops = 0.10
            elif ic >= 5 or td >= 6 or ef >= 6:
                min_devops = 0.08

    # Cap DevOps unless infra is present.
    max_devops = 0.22 if infra else 0.14

    split = _gemini_role_split(
        required_roles=required_roles,
        tech_stack=tech_stack,
        estimated_features_count=ef,
        tech_difficulty=td,
        integration_complexity=ic,
    )

    # Fallback deterministic split
    if split is None:
        if required_roles == {"BE"}:
            split = {"FE": 0.0, "BE": 1.0, "DEVOPS": 0.0}
        elif required_roles == {"FE"}:
            split = {"FE": 1.0, "BE": 0.0, "DEVOPS": 0.0}
        elif required_roles == {"DEVOPS"}:
            split = {"FE": 0.0, "BE": 0.0, "DEVOPS": 1.0}
        else:
            split = {"FE": 0.45, "BE": 0.55, "DEVOPS": 0.0}
        split = _normalize_split(split)

    # Enforce required role constraints for FE/BE
    if "FE" not in required_roles and split.get("FE", 0.0) > 0:
        split = {"FE": 0.0, "BE": split.get("BE", 0.0) + split.get("FE", 0.0), "DEVOPS": split.get("DEVOPS", 0.0)}
        split = _normalize_split(split)

    if "BE" not in required_roles and split.get("BE", 0.0) > 0:
        split = {"FE": split.get("FE", 0.0) + split.get("BE", 0.0), "BE": 0.0, "DEVOPS": split.get("DEVOPS", 0.0)}
        split = _normalize_split(split)

    # --- Post-process for realism ---
    split = _normalize_split(split)

    # Enforce minimum FE
    if min_fe > 0 and split["FE"] < min_fe:
        need = min_fe - split["FE"]
        from_be = min(need, split["BE"])
        split = {"FE": split["FE"] + from_be, "BE": split["BE"] - from_be, "DEVOPS": split["DEVOPS"]}
        need -= from_be
        if need > 1e-9:
            from_do = min(need, split["DEVOPS"])
            split = {"FE": split["FE"] + from_do, "BE": split["BE"], "DEVOPS": split["DEVOPS"] - from_do}
        split = _normalize_split(split)

    # Enforce DevOps min/cap
    if devops_allowed:
        if min_devops > 0 and split["DEVOPS"] < min_devops:
            need = min_devops - split["DEVOPS"]
            from_be = min(need, split["BE"])
            split = {"FE": split["FE"], "BE": split["BE"] - from_be, "DEVOPS": split["DEVOPS"] + from_be}
            need -= from_be
            if need > 1e-9:
                from_fe = min(need, split["FE"])
                split = {"FE": split["FE"] - from_fe, "BE": split["BE"], "DEVOPS": split["DEVOPS"] + from_fe}
            split = _normalize_split(split)

        if split["DEVOPS"] > max_devops:
            extra = split["DEVOPS"] - max_devops
            split = {"FE": split["FE"], "BE": split["BE"] + extra, "DEVOPS": max_devops}
            split = _normalize_split(split)
    else:
        if split["DEVOPS"] > 0:
            split = {"FE": split["FE"], "BE": split["BE"] + split["DEVOPS"], "DEVOPS": 0.0}
            split = _normalize_split(split)

    return split




def _recommendation_from_delta(
    *,
    role: str,
    delta_hours: float,
    working_days: int,
    assumed_seniority_mult: float = 1.0,
) -> dict[str, float | str]:
    """Turn +/- hours into a human recommendation.

    Positive delta means deficit (need more capacity).
    Negative delta means surplus (could cut).
    """
    if working_days <= 0:
        return {"role": role, "action": "unknown", "hours": float(delta_hours), "fte": 0.0}

    per_dev_capacity = working_days * HOURS_PER_DEV_PER_DAY * assumed_seniority_mult
    if per_dev_capacity <= 0:
        return {"role": role, "action": "unknown", "hours": float(delta_hours), "fte": 0.0}

    fte = abs(delta_hours) / per_dev_capacity
    action = "add" if delta_hours > 0 else "cut"
    return {"role": role, "action": action, "hours": float(abs(delta_hours)), "fte": float(fte)}


def run_estimation(project: Project) -> Project:
    """Populate derived fields and red-zone analysis."""
    reasons: list[str] = []

    # Clamp marks to 1..10 and provide reasonable fallbacks.
    marks = {
        "complexity_score": int(project.complexity_score or 4),
        "estimated_features_count": int(project.estimated_features_count or 4),
        "tech_difficulty": int(project.tech_difficulty or 4),
        "integration_complexity": int(project.integration_complexity or 4),
        "uncertainty_factor": int(project.uncertainty_factor or 4),
    }
    for k in list(marks.keys()):
        marks[k] = max(1, min(10, int(marks[k])))

    effort = compute_effort_hours(**marks)
    adjusted_score = compute_adjusted_effort_score(**marks)

    today = date.today()
    working_days = count_weekdays(today, project.deadline)
    devs = list(project.devs.all())

    if working_days <= 0:
        reasons.append("Deadline is today/past (no working days available).")
    if not devs:
        reasons.append("No developers provided (team is empty).")

    capacity_by_role = (
        compute_capacity_hours_by_role(devs, working_days)
        if working_days > 0 and devs
        else {"FE": 0.0, "BE": 0.0, "DEVOPS": 0.0}
    )
    capacity_total = float(sum(capacity_by_role.values()))

    required_roles = required_roles_from_stack(project.tech_stack or [])
    if "DEVOPS" in required_roles and not _has_devops_stack(project.tech_stack or []):
        required_roles = {r for r in required_roles if r != "DEVOPS"}
    # Realism: even without explicit infra keywords, web apps usually need some deploy/config/CI work.
    # Treat DEVOPS as effectively required if the stack implies it and the split gives it non-trivial hours.
    required_roles_effective = set(required_roles)
    if _has_devops_stack(project.tech_stack or []) or _has_light_devops_work(project.tech_stack or []):
        required_roles_effective.add("DEVOPS")
    have_roles = {d.role for d in devs}
    missing = [r for r in sorted(required_roles_effective) if r not in have_roles]
    if missing:
        reasons.append(f"Missing required roles for selected stack: {', '.join(missing)}.")

    split = compute_role_split_fractions(
        required_roles=required_roles,
        tech_stack=project.tech_stack or [],
        estimated_features_count=marks["estimated_features_count"],
        tech_difficulty=marks["tech_difficulty"],
        integration_complexity=marks["integration_complexity"],
    )
    # HARD STOP: if DevOps isn't required, force its effort share to 0
    if "DEVOPS" not in required_roles:
        split = {"FE": split.get("FE", 0.0), "BE": split.get("BE", 0.0) + split.get("DEVOPS", 0.0), "DEVOPS": 0.0}
        split = _normalize_split(split)
    effort_by_role = {k: float(effort * split.get(k, 0.0)) for k in ["FE", "BE", "DEVOPS"]}

    # Compute deltas and recommendations.
    delta_by_role = {
        k: float(effort_by_role.get(k, 0.0) - capacity_by_role.get(k, 0.0)) for k in ["FE", "BE", "DEVOPS"]
    }
    rec_by_role = {
        k: _recommendation_from_delta(role=k, delta_hours=delta_by_role[k], working_days=working_days)
        for k in ["FE", "BE", "DEVOPS"]
        if (effort_by_role.get(k, 0.0) > 0.0 or capacity_by_role.get(k, 0.0) > 0.0)
    }

    # Date estimate using total team capacity (regardless of role) – simple but stable.
    mult_sum = sum(SENIORITY_MULT.get(d.seniority, 1.0) for d in devs)
    daily_capacity_total = HOURS_PER_DEV_PER_DAY * mult_sum if mult_sum > 0 else 0.0
    if daily_capacity_total <= 0:
        days_needed = None
        finish_date = None
        reasons.append("Team capacity is zero (cannot estimate finish date).")
    else:
        days_needed = int(math.ceil(effort / daily_capacity_total))
        finish_date = add_workdays(today, days_needed)
        if finish_date > project.deadline:
            reasons.append(
                f"Estimated finish date {finish_date.isoformat()} exceeds deadline {project.deadline.isoformat()}."
            )

    # Red zone checks
    overall_deficit = capacity_total < effort

    # IMPORTANT: only count role deficits for REQUIRED roles (prevents false DEVOPS red-zone)
    role_deficits = [r for r, dh in delta_by_role.items() if (r in required_roles and dh > 0.01)]

    if overall_deficit:
        reasons.append(f"Capacity shortfall: need {effort:.0f}h, have {capacity_total:.0f}h until deadline.")
    if role_deficits:
        details = ", ".join(f"{r}: {delta_by_role[r]:.0f}h" for r in role_deficits)
        reasons.append(f"Role shortfall by labor category (hours): {details}.")

    project.adjusted_effort_score = adjusted_score
    project.effort_hours = float(effort)
    project.capacity_hours = float(capacity_total)
    project.effort_hours_by_role = effort_by_role
    project.capacity_hours_by_role = capacity_by_role
    project.labor_delta_hours_by_role = delta_by_role
    project.labor_recommendation_by_role = rec_by_role
    project.days_needed = days_needed
    project.estimated_finish_date = finish_date
    project.red_reasons = reasons
    project.red_zone = len(reasons) > 0

    project.save()
    return project