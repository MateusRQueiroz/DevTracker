from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from app.models import Dev, Project


HOURS_PER_DEV_PER_DAY = 6.0

COMPLEXITY_TO_EFFORT_HOURS = {
    1: 40,
    2: 80,
    3: 160,
    4: 320,
    5: 480,
}

SENIORITY_MULT = {
    "JUNIOR": 0.8,
    "MID": 1.0,
    "SENIOR": 1.2,
}


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5 


def count_weekdays(start: date, end: date) -> int:
    """
    Count weekdays from start to end inclusive.
    If end < start, returns 0.
    """
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
    """
    Add N weekdays to start (start is day 0).
    workdays=0 returns start.
    """
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
    """
    Very simple stack → required roles.
    """
    s = {x.strip().lower() for x in tech_stack if isinstance(x, str)}
    req: set[str] = set()

    if any(k in s for k in ["react", "vue", "angular", "frontend", "nextjs", "next.js"]):
        req.add("FE")

    if any(k in s for k in ["django", "flask", "fastapi", "backend", "node", "express"]):
        req.add("BE")

    if any(k in s for k in ["aws", "gcp", "azure", "docker", "k8s", "kubernetes", "ci", "cd", "terraform"]):
        req.add("DEVOPS")

    if not req:
        req.add("BE")

    return req


def compute_capacity_hours(devs: list[Dev], working_days_until_deadline: int) -> float:
    mult_sum = 0.0
    for d in devs:
        mult_sum += SENIORITY_MULT.get(d.seniority, 1.0)
    return working_days_until_deadline * HOURS_PER_DEV_PER_DAY * mult_sum


def run_estimation(project: Project) -> Project:
    """
    Populates:
    - effort_hours
    - capacity_hours
    - days_needed
    - estimated_finish_date
    - red_zone + reasons
    """
    reasons: list[str] = []

    c = int(project.complexity or 3)
    c = max(1, min(5, c))
    effort = float(COMPLEXITY_TO_EFFORT_HOURS[c])

    today = date.today()
    working_days = count_weekdays(today, project.deadline)
    devs = list(project.devs.all())

    if working_days <= 0:
        reasons.append("Deadline is today/past (no working days available).")

    if not devs:
        reasons.append("No developers provided (team is empty).")

    capacity = compute_capacity_hours(devs, working_days) if working_days > 0 and devs else 0.0

    required_roles = required_roles_from_stack(project.tech_stack or [])
    have_roles = {d.role for d in devs}

    missing = [r for r in sorted(required_roles) if r not in have_roles]
    if missing:
        reasons.append(f"Missing required roles for selected stack: {', '.join(missing)}.")

    mult_sum = sum(SENIORITY_MULT.get(d.seniority, 1.0) for d in devs)
    daily_capacity = HOURS_PER_DEV_PER_DAY * mult_sum if mult_sum > 0 else 0.0

    if daily_capacity <= 0:
        days_needed = None
        finish_date = None
        reasons.append("Team capacity is zero (cannot estimate finish date).")
    else:
        days_needed = int(math.ceil(effort / daily_capacity))
        finish_date = add_workdays(today, days_needed)

        if finish_date > project.deadline:
            reasons.append(
                f"Estimated finish date {finish_date.isoformat()} exceeds deadline {project.deadline.isoformat()}."
            )

    if capacity < effort:
        reasons.append(f"Capacity shortfall: need {effort:.0f}h, have {capacity:.0f}h until deadline.")

    project.effort_hours = effort
    project.capacity_hours = capacity
    project.days_needed = days_needed
    project.estimated_finish_date = finish_date
    project.red_reasons = reasons
    project.red_zone = len(reasons) > 0

    project.save()
    return project