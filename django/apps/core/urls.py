from django.urls import path

from .views import protected_media

urlpatterns = [
    # Uploaded documents with STORAGE_BACKEND=filesystem (404 otherwise).
    path("media/<path:path>", protected_media, name="protected_media"),
]
