from __future__ import annotations

import json
from datetime import date

from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt

from app.models import Dev, Project
from app.services.gemini import get_complexity
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

    complexity = get_complexity(title=title, description=description, tech_stack=tech_stack)
    project.complexity = complexity
    project.save()

    run_estimation(project)

    return JsonResponse(
        {
            "ok": True,
            "project_id": project.id,
            "red_zone": project.red_zone,
            "red_reasons": project.red_reasons,
            "complexity": project.complexity,
            "effort_hours": project.effort_hours,
            "capacity_hours": project.capacity_hours,
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
                "complexity": project.complexity,
                "effort_hours": project.effort_hours,
                "capacity_hours": project.capacity_hours,
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