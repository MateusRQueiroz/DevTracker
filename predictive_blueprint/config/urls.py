from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include

def health(_: object):
    return JsonResponse({"ok": True})

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("app.urls")),
]