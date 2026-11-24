from django.conf import settings
from django.urls import include, path, re_path

from . import views

urlpatterns = [
    path('api/health/', views.health),
    path('api/', include('accounts.urls')),
    path('api/', include('catalog.urls')),
    path('api/', include('monitoring.urls')),
    path('api/', include('backups.urls')),
    path('api/', include('domains.urls')),
]

if settings.DEBUG:
    from django.contrib import admin
    urlpatterns.append(path('admin/', admin.site.urls))

# Last: everything that isn't API (or admin) is a frontend route.
urlpatterns.append(re_path(r'^(?!api/|admin/|static/).*$', views.spa_index))
