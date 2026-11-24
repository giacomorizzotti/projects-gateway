from django.urls import path

from . import views

urlpatterns = [
    path('me/', views.me),
    path('auth/config/', views.auth_config),
]
