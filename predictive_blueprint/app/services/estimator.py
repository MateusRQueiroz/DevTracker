from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Iterable

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
    "uncertainty_factor": 8.0,  # treated as contingency/buffer hours
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
    """Very simple stack → required roles."""
    s = {x.strip().lower() for x in tech_stack if isinstance(x, str)}
    req: set[str] = set()

    if any(k in s for k in ["react", "vue", "angular", "frontend", "nextjs", "next.js", "ui"]):
        req.add("FE")

    if any(k in s for k in ["django", "flask", "fastapi", "backend", "node", "express", "api"]):
        req.add("BE")

    if any(
        k in s
        for k in [
            "aws",
            "gcp",
            "azure",
            "docker",
            "k8s",
            "kubernetes",
            "ci",
            "cd",
            "terraform",
            "devops",
        ]
    ):
        req.add("DEVOPS")

    # Default to backend if nothing obvious is selected.
    if not req:
        req.add("BE")
    return req


def _has_devops_stack(tech_stack: Iterable[str]) -> bool:
    s = {x.strip().lower() for x in tech_stack if isinstance(x, str)}
    return any(k in s for k in ["aws", "gcp", "azure", "docker", "k8s", "kubernetes", "terraform", "ci", "cd"])


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


def compute_role_split_fractions(
    *,
    required_roles: set[str],
    tech_stack: Iterable[str],
    estimated_features_count: int,
    tech_difficulty: int,
    integration_complexity: int,
) -> dict[str, float]:
    """Heuristic role split that varies with stack + marks.

    Returns fractions that sum to ~1 for roles in {FE, BE, DEVOPS}.
    """
    fe = 0.0
    be = 0.0
    devops = 0.0

    if required_roles == {"BE"}:
        be, devops = 0.85, 0.15
    elif required_roles == {"FE"}:
        fe, devops = 0.85, 0.15
    elif required_roles == {"DEVOPS"}:
        devops = 1.0
    else:
        # default full-stack split
        fe, be = 0.40, 0.50
        devops = 0.10

    # More features → more FE/BE work
    feat_boost = (max(1, min(10, estimated_features_count)) - 1) / 9.0  # 0..1
    fe += 0.05 * feat_boost
    be += 0.05 * feat_boost

    # More tech difficulty → more BE (architecture / tricky APIs)
    td_boost = (max(1, min(10, tech_difficulty)) - 1) / 9.0
    be += 0.08 * td_boost

    # Integration complexity + devops stack → more DevOps
    ic_boost = (max(1, min(10, integration_complexity)) - 1) / 9.0
    devops += 0.12 * ic_boost
    if _has_devops_stack(tech_stack):
        devops += 0.08

    # If FE not required, move FE share to BE.
    if "FE" not in required_roles and fe > 0:
        be += fe
        fe = 0.0

    # If BE not required, move BE share to FE.
    if "BE" not in required_roles and be > 0:
        fe += be
        be = 0.0

    # If DEVOPS not required and there is no devops stack, keep a tiny devops slice for CI/deploy.
    if "DEVOPS" not in required_roles and not _has_devops_stack(tech_stack):
        devops = min(devops, 0.05)

    # Normalize.
    total = fe + be + devops
    if total <= 0:
        return {"FE": 0.0, "BE": 1.0, "DEVOPS": 0.0}
    return {"FE": fe / total, "BE": be / total, "DEVOPS": devops / total}


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
        compute_capacity_hours_by_role(devs, working_days) if working_days > 0 and devs else {"FE": 0.0, "BE": 0.0, "DEVOPS": 0.0}
    )
    capacity_total = float(sum(capacity_by_role.values()))

    required_roles = required_roles_from_stack(project.tech_stack or [])
    have_roles = {d.role for d in devs}
    missing = [r for r in sorted(required_roles) if r not in have_roles]
    if missing:
        reasons.append(f"Missing required roles for selected stack: {', '.join(missing)}.")

    split = compute_role_split_fractions(
        required_roles=required_roles,
        tech_stack=project.tech_stack or [],
        estimated_features_count=marks["estimated_features_count"],
        tech_difficulty=marks["tech_difficulty"],
        integration_complexity=marks["integration_complexity"],
    )
    effort_by_role = {k: float(effort * split.get(k, 0.0)) for k in ["FE", "BE", "DEVOPS"]}

    # Compute deltas and recommendations.
    delta_by_role = {k: float(effort_by_role.get(k, 0.0) - capacity_by_role.get(k, 0.0)) for k in ["FE", "BE", "DEVOPS"]}
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

    # Red zone if any role deficit (or if overall deficit).
    overall_deficit = capacity_total < effort
    role_deficits = [r for r, dh in delta_by_role.items() if dh > 0.01]
    if overall_deficit:
        reasons.append(f"Capacity shortfall: need {effort:.0f}h, have {capacity_total:.0f}h until deadline.")
    if role_deficits:
        # Make it explicit: even if total hours are fine, wrong mix can still be a red zone.
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
