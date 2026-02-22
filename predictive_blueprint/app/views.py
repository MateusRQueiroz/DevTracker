from __future__ import annotations

import json
from datetime import date

from django.shortcuts import render
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt

from app.models import Dev, Project
from app.services.gemini import get_complexity_marks
from app.services.estimator import run_estimation


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


@csrf_exempt
def intake(request: HttpRequest) -> JsonResponse:
    """
    POST JSON body:
    {
      "title": "...",
      "description": "...",
      "tech_stack": ["Django", "React", "AWS"],
      "deadline": "2026-03-10",
      "team": [
        {"role": "BE", "seniority": "SENIOR"},
        {"role": "FE", "seniority": "MID"}
      ]
    }
    """
    if request.method != "POST":
        return _json_error("Use POST", 405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return _json_error("Invalid JSON body")

    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()
    tech_stack = payload.get("tech_stack", [])
    deadline_str = str(payload.get("deadline", "")).strip()
    team = payload.get("team", [])

    if not title:
        return _json_error("Missing 'title'")
    if not deadline_str:
        return _json_error("Missing 'deadline' (YYYY-MM-DD)")
    if not isinstance(tech_stack, list):
        return _json_error("'tech_stack' must be a list of strings")
    if not isinstance(team, list):
        return _json_error("'team' must be a list")

    try:
        deadline = date.fromisoformat(deadline_str)
    except ValueError:
        return _json_error("Deadline must be YYYY-MM-DD")

    project = Project.objects.create(
        title=title,
        description=description,
        tech_stack=tech_stack,
        deadline=deadline,
    )

    for member in team:
        role = str(member.get("role", "")).strip().upper()
        seniority = str(member.get("seniority", "")).strip().upper()

        if role not in {"FE", "BE", "DEVOPS"}:
            project.delete()
            return _json_error("Team role must be one of: FE, BE, DEVOPS")

        if seniority not in {"JUNIOR", "MID", "SENIOR"}:
            project.delete()
            return _json_error("Team seniority must be one of: JUNIOR, MID, SENIOR")

        Dev.objects.create(project=project, role=role, seniority=seniority)

    marks = get_complexity_marks(title=title, description=description, tech_stack=tech_stack)
    project.complexity_score = marks["complexity_score"]
    project.estimated_features_count = marks["estimated_features_count"]
    project.tech_difficulty = marks["tech_difficulty"]
    project.integration_complexity = marks["integration_complexity"]
    project.uncertainty_factor = marks["uncertainty_factor"]
    project.save()

    run_estimation(project)

    return JsonResponse(
        {
            "ok": True,
            "project_id": project.id,
            "red_zone": project.red_zone,
            "red_reasons": project.red_reasons,
            "marks": {
                "complexity_score": project.complexity_score,
                "estimated_features_count": project.estimated_features_count,
                "tech_difficulty": project.tech_difficulty,
                "integration_complexity": project.integration_complexity,
                "uncertainty_factor": project.uncertainty_factor,
            },
            "adjusted_effort_score": project.adjusted_effort_score,
            "effort_hours": project.effort_hours,
            "capacity_hours": project.capacity_hours,
            "effort_hours_by_role": project.effort_hours_by_role,
            "capacity_hours_by_role": project.capacity_hours_by_role,
            "labor_delta_hours_by_role": project.labor_delta_hours_by_role,
            "labor_recommendation_by_role": project.labor_recommendation_by_role,
            "days_needed": project.days_needed,
            "estimated_finish_date": project.estimated_finish_date.isoformat()
            if project.estimated_finish_date
            else None,
            "deadline": project.deadline.isoformat(),
        }
    )


def project_detail(request: HttpRequest, project_id: int) -> JsonResponse:
    if request.method != "GET":
        return _json_error("Use GET", 405)

    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return _json_error("Project not found", 404)

    devs = list(project.devs.all().values("role", "seniority"))

    return JsonResponse(
        {
            "ok": True,
            "project": {
                "id": project.id,
                "title": project.title,
                "description": project.description,
                "tech_stack": project.tech_stack,
                "deadline": project.deadline.isoformat(),
                "marks": {
                    "complexity_score": project.complexity_score,
                    "estimated_features_count": project.estimated_features_count,
                    "tech_difficulty": project.tech_difficulty,
                    "integration_complexity": project.integration_complexity,
                    "uncertainty_factor": project.uncertainty_factor,
                },
                "adjusted_effort_score": project.adjusted_effort_score,
                "effort_hours": project.effort_hours,
                "capacity_hours": project.capacity_hours,
                "effort_hours_by_role": project.effort_hours_by_role,
                "capacity_hours_by_role": project.capacity_hours_by_role,
                "labor_delta_hours_by_role": project.labor_delta_hours_by_role,
                "labor_recommendation_by_role": project.labor_recommendation_by_role,
                "days_needed": project.days_needed,
                "estimated_finish_date": project.estimated_finish_date.isoformat()
                if project.estimated_finish_date
                else None,
                "red_zone": project.red_zone,
                "red_reasons": project.red_reasons,
                "team": devs,
            }
        }
    )


# ------------------------------
# Frontend pages (HTML dashboard)
# ------------------------------


def home(request: HttpRequest):
    """Landing page with the intake form."""
    return render(request, "app/index.html")


def dashboard(request: HttpRequest):
    """Simple dashboard listing all projects."""
    projects = Project.objects.all().order_by("-created_at")
    return render(request, "app/dashboard.html", {"projects": projects})


def project_page(request: HttpRequest, project_id: int):
    """Human-friendly project detail page."""
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return render(request, "app/not_found.html", status=404)

    devs = list(project.devs.all().values("role", "seniority"))

    deadline_iso = project.deadline.isoformat() if project.deadline else ""
    finish_iso = (
        project.estimated_finish_date.isoformat() if project.estimated_finish_date else ""
    )

    effort_by_role_json = json.dumps(project.effort_hours_by_role or {})
    capacity_by_role_json = json.dumps(project.capacity_hours_by_role or {})

    return render(
        request,
        "app/project_detail.html",
        {
            "project": project,
            "team": devs,
            "deadline_iso": deadline_iso,
            "finish_iso": finish_iso,
            "effort_by_role_json": effort_by_role_json,
            "capacity_by_role_json": capacity_by_role_json,
        },
    )