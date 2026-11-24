from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register('projects', views.ProjectViewSet, basename='project')
router.register('platforms', views.PlatformViewSet, basename='platform')
router.register('environments', views.EnvironmentViewSet)
router.register('repositories', views.RepositoryViewSet)
router.register('clients', views.ClientViewSet)
router.register('groups', views.ProjectGroupViewSet)
router.register('technologies', views.TechnologyViewSet)
router.register('technology-categories', views.TechnologyCategoryViewSet)
router.register('platform-kinds', views.PlatformKindViewSet)
router.register('repository-hostings', views.RepositoryHostingViewSet)
router.register('dependencies', views.DependencyViewSet)
router.register('services', views.ServiceViewSet)
router.register('links', views.LinkViewSet)

urlpatterns = [
    path('choices/', views.choices),
    path('github/', views.github_status),
    path('github/sync/', views.github_sync),
] + router.urls
