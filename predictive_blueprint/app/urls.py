from django.urls import path
from app import views

urlpatterns = [
    # Frontend pages
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("projects/<int:project_id>/", views.project_page, name="project_page"),

    # JSON API
    path("api/intake/", views.intake),
    path("api/project/<int:project_id>/", views.project_detail),
    path("api/key/", views.api_key),
]