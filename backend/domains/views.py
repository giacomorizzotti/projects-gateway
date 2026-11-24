from urllib.parse import urlsplit

from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from catalog.models import Environment
from . import registry
from .models import Domain
from .serializers import DomainSerializer, _brief


def _environments():
    return list(Environment.objects.select_related('project'))


class DomainViewSet(viewsets.ModelViewSet):
    serializer_class = DomainSerializer

    def get_queryset(self):
        return Domain.objects.select_related('client', 'registrar_service', 'dns_service').prefetch_related('projects')

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'environments': _environments()}

    def perform_create(self, serializer):
        # Ask the registry straight away: one request, and the row arrives filled in.
        registry.refresh(serializer.save())

    @action(detail=True, methods=['post'])
    def refresh(self, request, pk=None):
        domain = self.get_object()
        registry.refresh(domain)
        return Response(self.get_serializer(domain).data)


@api_view(['GET'])
def suggestions(request):
    """Registered names in the catalog's URLs that aren't tracked yet, with what uses them:
    the "+ Track" list (only the ones that are mine get tracked)."""
    tracked = set(Domain.objects.values_list('name', flat=True))
    found = {}
    for env in _environments():
        for url in env.urls:
            host = (urlsplit(url).hostname or '').lower()
            name = registry.registered_name(host)
            if not name or name in tracked or host == 'localhost' or host.replace('.', '').isdigit():
                continue
            entry = found.setdefault(name, {'name': name, 'hosts': set(), 'projects': {}})
            entry['hosts'].add(host)
            entry['projects'][env.project_id] = _brief(env.project)
    return Response([{'name': e['name'], 'hosts': sorted(e['hosts']),
                      'projects': sorted(e['projects'].values(), key=lambda p: p['name'].lower())}
                     for e in sorted(found.values(), key=lambda e: e['name'])])
