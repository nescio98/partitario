from django.urls import path

from . import views

# Mounted at /accounts/, before allauth's own URLs (config/urls.py).
urlpatterns = [
    path("", views.manage, name="account_manage"),
    path("delete/", views.delete, name="account_delete"),
]
