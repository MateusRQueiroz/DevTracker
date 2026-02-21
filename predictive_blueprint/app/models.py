from __future__ import annotations

from django.db import models
from django.utils import timezone


class Project(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    tech_stack = models.JSONField(default=list, blank=True)

    deadline = models.DateField()

    complexity = models.PositiveSmallIntegerField(null=True, blank=True)  # 1..5
    effort_hours = models.FloatField(null=True, blank=True)
    capacity_hours = models.FloatField(null=True, blank=True)

    days_needed = models.PositiveIntegerField(null=True, blank=True)
    estimated_finish_date = models.DateField(null=True, blank=True)

    red_zone = models.BooleanField(default=False)
    red_reasons = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"{self.title} (id={self.id})"


class Dev(models.Model):
    class Role(models.TextChoices):
        FE = "FE", "Frontend"
        BE = "BE", "Backend"
        DEVOPS = "DEVOPS", "DevOps"

    class Seniority(models.TextChoices):
        JUNIOR = "JUNIOR", "Junior"
        MID = "MID", "Mid"
        SENIOR = "SENIOR", "Senior"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="devs")
    role = models.CharField(max_length=10, choices=Role.choices)
    seniority = models.CharField(max_length=10, choices=Seniority.choices)

    def __str__(self) -> str:
        return f"{self.role}/{self.seniority} (project={self.project_id})"