from django.urls import path

from . import views

urlpatterns = [
    path('status/', views.status),
    path('status/check/', views.check_now),
]
