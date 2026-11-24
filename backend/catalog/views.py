import django_filters
from django.db import transaction
from django.db.models import Count, Prefetch
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from . import github
from . import serializers as s
from .models import (Client, Dependency, Environment, Link, Platform, PlatformKind, Project, ProjectGroup,
                     Repository, RepositoryHosting, Service, Technology, TechnologyCategory)


class ProjectFilter(django_filters.FilterSet):
    platform = django_filters.CharFilter(field_name='environments__platform__slug', distinct=True)
    technology = django_filters.CharFilter(field_name='technologies__name', distinct=True)
    client = django_filters.CharFilter(field_name='client__slug')

    class Meta:
        model = Project
        fields = ['group', 'status', 'client', 'platform', 'technology']


class ProjectViewSet(viewsets.ModelViewSet):
    lookup_field = 'slug'
    filterset_class = ProjectFilter
    search_fields = ['name', 'description', 'client__name']
    ordering_fields = ['name', 'group', 'status']

    def get_queryset(self):
        qs = Project.objects.select_related('client').prefetch_related(
            'technologies',
            'repositories',
            'services',
            Prefetch('environments', queryset=Environment.objects.select_related('platform')),
        )
        if self.action == 'retrieve':
            qs = qs.prefetch_related(
                'links',
                Prefetch('dependencies', queryset=Dependency.objects.select_related('project', 'depends_on', 'environment')),
                Prefetch('dependents', queryset=Dependency.objects.select_related('project', 'depends_on', 'environment')),
            )
        return qs

    def get_serializer_class(self):
        return s.ProjectDetailSerializer if self.action == 'retrieve' else s.ProjectSerializer


class PlatformViewSet(viewsets.ModelViewSet):
    lookup_field = 'slug'
    filterset_fields = ['kind']
    search_fields = ['name', 'provider', 'location']

    def get_queryset(self):
        # One prefetch of `environments` only: prefetching the same relation twice raises a
        # ValueError, which DRF's get_object turns into a misleading 404.
        environments = Environment.objects.select_related('project', 'platform').order_by(
            'project__name', 'position')
        return Platform.objects.prefetch_related('links', Prefetch('environments', queryset=environments))

    def get_serializer_class(self):
        return s.PlatformDetailSerializer if self.action == 'retrieve' else s.PlatformSerializer


class EnvironmentViewSet(viewsets.ModelViewSet):
    queryset = Environment.objects.select_related('project', 'platform')
    serializer_class = s.EnvironmentWithProjectSerializer
    filterset_fields = ['project', 'platform', 'kind']


class RepositoryViewSet(viewsets.ModelViewSet):
    lookup_field = 'slug'
    queryset = Repository.objects.prefetch_related('projects')
    serializer_class = s.RepositorySerializer
    filterset_fields = ['hosting', 'private', 'archived']
    search_fields = ['name', 'remote_url', 'local_path']


class ClientViewSet(viewsets.ModelViewSet):
    # Deleting one leaves its projects and domains with no client (SET_NULL).
    queryset = Client.objects.annotate(project_count=Count('projects', distinct=True),
                                       domain_count=Count('domains', distinct=True))
    serializer_class = s.ClientSerializer


class TechnologyViewSet(viewsets.ModelViewSet):
    queryset = Technology.objects.annotate(project_count=Count('projects', distinct=True))
    serializer_class = s.TechnologySerializer
    filterset_fields = ['category']


class TechnologyCategoryViewSet(viewsets.ModelViewSet):
    """The technologies' categories (Settings page). One with technologies in it can't be
    deleted: they'd be left in a category that doesn't exist."""
    queryset = TechnologyCategory.objects.all()
    serializer_class = s.TechnologyCategorySerializer

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        used = Technology.objects.filter(category=category.slug).count()
        if used:
            return Response({'detail': f'{used} technolog{"ies are" if used != 1 else "y is"} in {category.name}: '
                                       'move them to another category first.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class PlatformKindViewSet(viewsets.ModelViewSet):
    """The platforms' kinds (Settings page). One with platforms can't be deleted: they'd be left
    with a kind that doesn't exist."""
    queryset = PlatformKind.objects.all()
    serializer_class = s.PlatformKindSerializer

    def destroy(self, request, *args, **kwargs):
        kind = self.get_object()
        used = Platform.objects.filter(kind=kind.slug).count()
        if used:
            return Response({'detail': f'{used} platform{"s are" if used != 1 else " is"} {kind.name}: '
                                       'give them another kind first.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class RepositoryHostingViewSet(viewsets.ModelViewSet):
    """Where repositories are hosted (Settings page). One with repositories can't be deleted:
    they'd be left with a hosting that doesn't exist."""
    queryset = RepositoryHosting.objects.all()
    serializer_class = s.RepositoryHostingSerializer

    def destroy(self, request, *args, **kwargs):
        hosting = self.get_object()
        used = Repository.objects.filter(hosting=hosting.slug).count()
        if used:
            return Response({'detail': f'{used} repositor{"ies are" if used != 1 else "y is"} on {hosting.name}: '
                                       'move them to another hosting first.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class DependencyViewSet(viewsets.ModelViewSet):
    queryset = Dependency.objects.select_related('project', 'depends_on', 'environment')
    serializer_class = s.DependencySerializer
    filterset_fields = ['project', 'depends_on', 'kind', 'via']


class ProjectGroupViewSet(viewsets.ModelViewSet):
    """The dashboard's groups (Settings page). A group with projects in it can't be deleted:
    they'd be left in a group that doesn't exist."""
    queryset = ProjectGroup.objects.all()
    serializer_class = s.ProjectGroupSerializer

    def destroy(self, request, *args, **kwargs):
        group = self.get_object()
        used = Project.objects.filter(group=group.slug).count()
        if used:
            return Response({'detail': f'{used} project{"s are" if used != 1 else " is"} in {group.name}: '
                                       'move them to another group first.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """{"ids": [every group's id, in the new order]}."""
        ids = request.data.get('ids')
        groups = {g.id: g for g in ProjectGroup.objects.all()}
        if not isinstance(ids, list) or sorted(ids) != sorted(groups):
            return Response({'detail': 'Send every group’s id, once each.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for position, pk in enumerate(ids, 1):
                if groups[pk].position != position:
                    groups[pk].position = position
                    groups[pk].save(update_fields=['position'])
        return Response(s.ProjectGroupSerializer(ProjectGroup.objects.all(), many=True).data)


class ServiceViewSet(viewsets.ModelViewSet):
    lookup_field = 'slug'
    queryset = Service.objects.prefetch_related('projects')
    serializer_class = s.ServiceSerializer


class LinkViewSet(viewsets.ModelViewSet):
    queryset = Link.objects.all()
    serializer_class = s.LinkSerializer
    filterset_fields = ['project', 'platform']


@api_view(['GET'])
def choices(request):
    """The value lists (groups, statuses, kinds…), for the frontend's labels and forms. Groups,
    platform kinds, repository hostings and technology categories come from the database (Settings
    page); the others are fixed in the code."""
    def opts(enum):
        return [{'value': v, 'label': label} for v, label in enum.choices]
    return Response({
        'project_groups': [{'value': g.slug, 'label': g.name, 'hidden': g.hidden} for g in ProjectGroup.objects.all()],
        'project_statuses': opts(Project.Status),
        'platform_kinds': [{'value': k.slug, 'label': k.name} for k in PlatformKind.objects.all()],
        'environment_kinds': opts(Environment.Kind),
        'repository_hostings': [{'value': h.slug, 'label': h.name} for h in RepositoryHosting.objects.all()],
        'technology_categories': [{'value': c.slug, 'label': c.name} for c in TechnologyCategory.objects.all()],
        'dependency_kinds': opts(Dependency.Kind),
        'dependency_vias': opts(Dependency.Via),
    })


@api_view(['GET'])
def github_status(request):
    return Response(github.status())


@api_view(['POST'])
def github_sync(request):
    """"Sync now". A couple of GitHub requests, so it runs inside the request."""
    try:
        result = github.sync()
    except github.GitHubError as e:
        return Response({**github.status(), 'detail': str(e)}, status=502)
    return Response({**github.status(), 'result': result})
