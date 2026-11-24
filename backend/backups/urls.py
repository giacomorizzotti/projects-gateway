from django.urls import path
from rest_framework.routers import DefaultRouter

from . import agent_api, views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register('backup-targets', views.BackupTargetViewSet)
router.register('backup-jobs', views.BackupJobViewSet, basename='backupjob')
router.register('backup-runs', views.BackupRunViewSet)

urlpatterns = [
    path('backups/', views.overview),
    # The agents' own API (their token, not a login).
    path('agent/checkin/', agent_api.checkin),
    path('agent/runs/', agent_api.report_run),
    path('agent/report/', agent_api.report),
] + router.urls
