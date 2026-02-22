from __future__ import annotations

import json
from datetime import date

from django.db.models import Q
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction

from app.models import Dev, Project
from app.services.gemini import get_complexity_marks
from app.services.estimator import run_estimation


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _is_json_request(request: HttpRequest) -> bool:
    ct = (request.content_type or "").lower()
    # handles "application/json" and "application/json; charset=utf-8"
    return "application/json" in ct


def _parse_payload(request: HttpRequest) -> tuple[dict, bool] | tuple[None, bool]:
    """
    Returns (payload, is_json). payload is dict. If invalid JSON, returns (None, True).
    """
    is_json = _is_json_request(request)
    if is_json:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                return None, True
            return payload, True
        except Exception:
            return None, True

    # form POST fallback
    payload = dict(request.POST.items())
    # allow tech_stack as "a,b,c"
    if "tech_stack" in payload:
        payload["tech_stack"] = [
            s.strip()
            for s in (payload.get("tech_stack") or "").split(",")
            if s.strip()
        ]
    return payload, False


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

    with transaction.atomic():
        project = Project.objects.create(
            title=title,
            description=description,
            tech_stack=[str(x).strip() for x in tech_stack if str(x).strip()],
            deadline=deadline,
        )

        for member in team:
            if not isinstance(member, dict):
                transaction.set_rollback(True)
                return _json_error("Each team member must be an object with role/seniority")

            role = str(member.get("role", "")).strip().upper()
            seniority = str(member.get("seniority", "")).strip().upper()

            if role not in {"FE", "BE", "DEVOPS"}:
                transaction.set_rollback(True)
                return _json_error("Team role must be one of: FE, BE, DEVOPS")

            if seniority not in {"JUNIOR", "MID", "SENIOR"}:
                transaction.set_rollback(True)
                return _json_error("Team seniority must be one of: JUNIOR, MID, SENIOR")

            Dev.objects.create(project=project, role=role, seniority=seniority)

        marks = get_complexity_marks(title=title, description=description, tech_stack=project.tech_stack)
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
        }
    )


@csrf_exempt
def project_detail(request: HttpRequest, project_id: int) -> JsonResponse:
    """
    GET -> project JSON
    PUT/PATCH/POST -> update fields + re-run estimation
    - re-run Gemini marks if title/desc/stack changed
    - update team if "team" is provided
    DELETE -> delete project
    """
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return _json_error("Project not found", 404)

    if request.method == "GET":
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

    if request.method in {"PUT", "PATCH", "POST"}:
        parsed, is_json = _parse_payload(request)
        if parsed is None and is_json:
            return _json_error("Invalid JSON body")

        payload = parsed or {}

        rerun_gemini = False

        with transaction.atomic():
            # --- fields ---
            if "title" in payload:
                title = str(payload.get("title", "")).strip()
                if not title:
                    return _json_error("Title cannot be empty")
                if title != project.title:
                    project.title = title
                    rerun_gemini = True

            if "description" in payload:
                desc = str(payload.get("description", "")).strip()
                if desc != (project.description or ""):
                    project.description = desc
                    rerun_gemini = True

            if "tech_stack" in payload:
                tech_stack = payload.get("tech_stack", [])
                if isinstance(tech_stack, str):
                    tech_stack = [s.strip() for s in tech_stack.split(",") if s.strip()]
                if not isinstance(tech_stack, list):
                    return _json_error("'tech_stack' must be a list of strings")
                cleaned = [str(x).strip() for x in tech_stack if str(x).strip()]
                if cleaned != (project.tech_stack or []):
                    project.tech_stack = cleaned
                    rerun_gemini = True

            if "deadline" in payload:
                deadline_str = str(payload.get("deadline", "")).strip()
                if not deadline_str:
                    return _json_error("Deadline cannot be empty (YYYY-MM-DD)")
                try:
                    new_deadline = date.fromisoformat(deadline_str)
                except ValueError:
                    return _json_error("Deadline must be YYYY-MM-DD")
                if new_deadline != project.deadline:
                    project.deadline = new_deadline

            # --- team updates ---
            if "team" in payload:
                team = payload.get("team", [])
                if not isinstance(team, list):
                    return _json_error("'team' must be a list")

                # Replace roster fully (simple + reliable)
                project.devs.all().delete()

                for member in team:
                    if not isinstance(member, dict):
                        return _json_error("Each team member must be an object with role/seniority")

                    role = str(member.get("role", "")).strip().upper()
                    seniority = str(member.get("seniority", "")).strip().upper()

                    if role not in {"FE", "BE", "DEVOPS"}:
                        return _json_error("Team role must be one of: FE, BE, DEVOPS")

                    if seniority not in {"JUNIOR", "MID", "SENIOR"}:
                        return _json_error("Team seniority must be one of: JUNIOR, MID, SENIOR")

                    Dev.objects.create(project=project, role=role, seniority=seniority)

            project.save()

            # --- recompute marks if needed ---
            if rerun_gemini:
                marks = get_complexity_marks(
                    title=project.title,
                    description=project.description or "",
                    tech_stack=project.tech_stack or [],
                )
                project.complexity_score = marks["complexity_score"]
                project.estimated_features_count = marks["estimated_features_count"]
                project.tech_difficulty = marks["tech_difficulty"]
                project.integration_complexity = marks["integration_complexity"]
                project.uncertainty_factor = marks["uncertainty_factor"]
                project.save()

            # Always re-run estimation after any update (team/deadline/marks/etc.)
            run_estimation(project)

        if is_json:
            return JsonResponse(
                {
                    "ok": True,
                    "project_id": project.id,
                    "red_zone": project.red_zone,
                    "red_reasons": project.red_reasons,
                }
            )

        return redirect("project_page", project_id=project.id)

    if request.method == "DELETE":
        project.delete()
        return JsonResponse({"ok": True})

    return _json_error("Method not allowed", 405)


# ------------------------------
# Frontend pages (HTML)
# ------------------------------

def home(request: HttpRequest):
    return render(request, "app/index.html")


def dashboard(request: HttpRequest):
    q = str(request.GET.get("q", "")).strip()

    projects = Project.objects.all()
    if q:
        projects = projects.filter(Q(title__icontains=q) | Q(description__icontains=q))

    projects = projects.order_by("-created_at")
    return render(request, "app/dashboard.html", {"projects": projects, "q": q})


def project_page(request: HttpRequest, project_id: int):
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return render(request, "app/not_found.html", status=404)

    devs = list(project.devs.all().values("role", "seniority"))

    deadline_iso = project.deadline.isoformat() if project.deadline else ""
    effort_by_role_json = json.dumps(project.effort_hours_by_role or {})
    capacity_by_role_json = json.dumps(project.capacity_hours_by_role or {})

    return render(
        request,
        "app/project_detail.html",
        {
            "project": project,
            "team": devs,
            "deadline_iso": deadline_iso,
            "effort_by_role_json": effort_by_role_json,
            "capacity_by_role_json": capacity_by_role_json,
        },
    )