"""Django admin: development only (the admin app is installed only when DJANGO_DEBUG=True)."""
from django.contrib import admin

from .models import (Client, Dependency, Environment, Link, Platform, Project, Repository,
                     Service, Technology, TechnologyCategory)


class EnvironmentInline(admin.TabularInline):
    model = Environment
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'group', 'status', 'client']
    list_filter = ['group', 'status']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ['name']}
    inlines = [EnvironmentInline]


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ['name', 'kind', 'provider', 'location']
    prepopulated_fields = {'slug': ['name']}


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'hosting', 'private', 'local_path']
    list_filter = ['hosting', 'private']
    prepopulated_fields = {'slug': ['name']}


admin.site.register([Client, Technology, TechnologyCategory, Dependency, Service, Link, Environment])
