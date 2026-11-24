from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register('domains', views.DomainViewSet, basename='domain')

urlpatterns = [
    path('domains/suggestions/', views.suggestions),
] + router.urls
