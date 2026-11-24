import re
from urllib.parse import urlsplit

from rest_framework import serializers

from catalog.models import Project
from .models import Domain
from .registry import days_left

NAME = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$')


def _brief(project):
    return {'id': project.id, 'slug': project.slug, 'name': project.name}


def _service(service):
    return service and {'id': service.id, 'slug': service.slug, 'name': service.name, 'url': service.url,
                        'account': service.account}


class DomainSerializer(serializers.ModelSerializer):
    """`sites` and the derived projects need the catalog's environments: the view passes
    them in the context (`environments`), loaded once for the whole list."""

    client_name = serializers.CharField(source='client.name', read_only=True, default=None)
    days_left = serializers.SerializerMethodField()
    sites = serializers.SerializerMethodField()
    project_details = serializers.SerializerMethodField()
    projects = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=Project.objects.all())
    registrar_service_details = serializers.SerializerMethodField()
    dns_service_details = serializers.SerializerMethodField()

    class Meta:
        model = Domain
        fields = ['id', 'name', 'registrar', 'dns_provider', 'registrar_service', 'registrar_service_details',
                  'dns_service', 'dns_service_details', 'client', 'client_name', 'projects', 'project_details',
                  'auto_renew', 'expires_on', 'expires_by_hand', 'days_left', 'registered_on', 'nameservers',
                  'registry_status', 'looked_up_at', 'lookup_error', 'sites', 'notes']
        # registrar and dns_provider are the registry's words; the choice is the two services.
        read_only_fields = ['registrar', 'dns_provider', 'expires_by_hand', 'registered_on', 'nameservers',
                            'registry_status', 'looked_up_at', 'lookup_error']

    def validate_name(self, value):
        value = value.strip().lower().rstrip('.')
        if value.startswith('www.'):
            value = value[4:]
        if not NAME.match(value):
            raise serializers.ValidationError('A domain name, like example.com.')
        return value

    def validate(self, attrs):
        # A date written here is typed by hand: lookups then leave it (unless the registry
        # publishes one, which wins).
        changed = 'expires_on' in attrs and (self.instance is None or attrs['expires_on'] != self.instance.expires_on)
        if changed:
            attrs['expires_by_hand'] = attrs['expires_on'] is not None
        return attrs

    def get_days_left(self, obj):
        return days_left(obj.expires_on)

    def get_registrar_service_details(self, obj):
        return _service(obj.registrar_service)

    def get_dns_service_details(self, obj):
        return _service(obj.dns_service)

    def _sites(self, obj):
        out = []
        for env in self.context.get('environments', []):
            for url in env.urls:
                host = urlsplit(url).hostname
                if obj.covers(host):
                    out.append({'host': host, 'url': url, 'environment': env.name, 'project': _brief(env.project)})
        return out

    def get_sites(self, obj):
        return self._sites(obj)

    def get_project_details(self, obj):
        found = {p.id: _brief(p) for p in obj.projects.all()}
        for site in self._sites(obj):
            found.setdefault(site['project']['id'], site['project'])
        return sorted(found.values(), key=lambda p: p['name'].lower())
