from django.urls import path
from app import views

urlpatterns = [
    path("api/intake/", views.intake),
    path("api/project/<int:project_id>/", views.project_detail),
]