from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

def health(_: object):
    return JsonResponse({"ok": True})

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("app.urls")),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)