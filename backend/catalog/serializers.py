"""API representations.

Writes use primary keys for relations (client, platform, technologies…). Reads also include
small nested "brief" objects so the frontend can render pages without extra requests.
"""
import ipaddress

from django.core.validators import URLValidator
from django.db.models import Max
from rest_framework import serializers

from .models import (Client, Dependency, Environment, Link, Platform, Project, ProjectGroup, Repository,
                     Service, Technology, TechnologyCategory)
from .utils import unique_slug


class AutoSlugMixin:
    """`slug` may be left out (or blank) on create: it then comes from the name.

    On update a blank slug keeps the current one. A changed slug changes the object's URL.
    """

    def get_fields(self):
        fields = super().get_fields()
        fields['slug'].required = False
        fields['slug'].allow_blank = True
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs.get('slug'):
            attrs.pop('slug', None)
            if self.instance is None:
                attrs['slug'] = unique_slug(self.Meta.model, attrs.get('name', ''))
        return attrs


def next_position(queryset):
    return (queryset.aggregate(m=Max('position'))['m'] or 0) + 1


_http_url = URLValidator(schemes=['http', 'https'])


class PlatformBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = ['id', 'slug', 'name', 'kind']


class ProjectBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'slug', 'name', 'group', 'status']


class RepositoryBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repository
        fields = ['id', 'slug', 'name', 'hosting', 'remote_url', 'private', 'github_url',
                  'archived', 'language', 'pushed_at']


def _count(obj, name, related):
    """An annotated count (the list views add them), or counted now (after a create)."""
    value = getattr(obj, name, None)
    return getattr(obj, related).count() if value is None else value


class ClientSerializer(AutoSlugMixin, serializers.ModelSerializer):
    # What deleting one changes: those projects and domains are left with no client.
    project_count = serializers.SerializerMethodField()
    domain_count = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = ['id', 'name', 'slug', 'project_count', 'domain_count']

    def get_project_count(self, obj):
        return _count(obj, 'project_count', 'projects')

    def get_domain_count(self, obj):
        return _count(obj, 'domain_count', 'domains')


class TechnologySerializer(serializers.ModelSerializer):
    project_count = serializers.SerializerMethodField()

    class Meta:
        model = Technology
        fields = ['id', 'name', 'category', 'project_count']

    def get_project_count(self, obj):
        return _count(obj, 'project_count', 'projects')

    def validate_category(self, value):
        if value and not TechnologyCategory.objects.filter(slug=value).exists():
            raise serializers.ValidationError('No such category: add it on the Settings page first.')
        return value

    def create(self, validated_data):
        # A technology created on the spot (the project form sends only its name).
        if 'category' not in validated_data and TechnologyCategory.objects.filter(slug='other').exists():
            validated_data['category'] = 'other'
        return super().create(validated_data)


class TechnologyCategorySerializer(serializers.ModelSerializer):
    """The slug is made from the first name and then never changes: technologies keep it."""
    technology_count = serializers.SerializerMethodField()

    class Meta:
        model = TechnologyCategory
        fields = ['id', 'name', 'slug', 'technology_count']
        read_only_fields = ['slug']

    def get_technology_count(self, obj):
        return Technology.objects.filter(category=obj.slug).count()

    def create(self, validated_data):
        validated_data['slug'] = unique_slug(TechnologyCategory, validated_data['name'])
        return super().create(validated_data)


class ProjectGroupSerializer(serializers.ModelSerializer):
    """The slug is made from the first name and then never changes: projects keep it."""
    project_count = serializers.SerializerMethodField()

    class Meta:
        model = ProjectGroup
        fields = ['id', 'name', 'slug', 'position', 'hidden', 'project_count']
        read_only_fields = ['slug', 'position']

    def get_project_count(self, obj):
        return Project.objects.filter(group=obj.slug).count()

    def create(self, validated_data):
        validated_data['slug'] = unique_slug(ProjectGroup, validated_data['name'])
        validated_data['position'] = next_position(ProjectGroup.objects.all())
        return super().create(validated_data)


class LinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Link
        fields = ['id', 'label', 'url', 'project', 'platform', 'position']
        extra_kwargs = {'position': {'required': False}}

    def validate(self, attrs):
        project = attrs.get('project', getattr(self.instance, 'project', None))
        platform = attrs.get('platform', getattr(self.instance, 'platform', None))
        if bool(project) == bool(platform):
            raise serializers.ValidationError('A link belongs to exactly one project or one platform.')
        return attrs

    def create(self, validated_data):
        # New links go last.
        if 'position' not in validated_data:
            owner = ({'project': validated_data['project']} if validated_data.get('project')
                     else {'platform': validated_data['platform']})
            validated_data['position'] = next_position(Link.objects.filter(**owner))
        return super().create(validated_data)


class EnvironmentSerializer(serializers.ModelSerializer):
    platform_detail = PlatformBriefSerializer(source='platform', read_only=True)
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)

    class Meta:
        model = Environment
        fields = ['id', 'project', 'name', 'kind', 'kind_label', 'urls', 'platform', 'platform_detail',
                  'runtime', 'path', 'deploy', 'checks_enabled', 'notes', 'position']
        extra_kwargs = {'position': {'required': False}}

    def validate_urls(self, value):
        if not isinstance(value, list) or not all(isinstance(u, str) for u in value):
            raise serializers.ValidationError('A list of URLs is expected.')
        urls = [u.strip() for u in value if u.strip()]
        for url in urls:
            try:
                _http_url(url)
            except Exception:
                raise serializers.ValidationError(f'"{url}" is not an http(s) URL.')
        return urls

    def create(self, validated_data):
        # New environments go last in their project.
        if 'position' not in validated_data:
            validated_data['position'] = next_position(
                Environment.objects.filter(project=validated_data['project']))
        return super().create(validated_data)


class EnvironmentWithProjectSerializer(EnvironmentSerializer):
    project_detail = ProjectBriefSerializer(source='project', read_only=True)

    class Meta(EnvironmentSerializer.Meta):
        fields = EnvironmentSerializer.Meta.fields + ['project_detail']


class ProjectSerializer(AutoSlugMixin, serializers.ModelSerializer):
    group_label = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True, default=None)
    technology_names = serializers.SlugRelatedField(source='technologies', slug_field='name',
                                                    many=True, read_only=True)
    environments = EnvironmentSerializer(many=True, read_only=True)
    repositories = RepositoryBriefSerializer(many=True, read_only=True)
    # Repos and services point at projects (the M2M lives on them), but a project form
    # sets them too: these are the writable id lists of the same relations.
    repository_ids = serializers.PrimaryKeyRelatedField(
        source='repositories', many=True, required=False, queryset=Repository.objects.all())
    service_ids = serializers.PrimaryKeyRelatedField(
        source='services', many=True, required=False, queryset=Service.objects.all())

    class Meta:
        model = Project
        fields = ['id', 'slug', 'name', 'group', 'group_label', 'status', 'status_label', 'client',
                  'client_name', 'description', 'notes', 'notes_markdown', 'technologies', 'technology_names',
                  'environments', 'repositories', 'repository_ids', 'service_ids']

    def get_group_label(self, obj):
        # Read once per request: the dashboard lists every project.
        names = self.context.get('_group_names')
        if names is None:
            names = self.context['_group_names'] = dict(ProjectGroup.objects.values_list('slug', 'name'))
        return names.get(obj.group, obj.group)

    def validate_group(self, value):
        if not ProjectGroup.objects.filter(slug=value).exists():
            raise serializers.ValidationError('No such group: add it on the Settings page first.')
        return value


class DependencySerializer(serializers.ModelSerializer):
    project_detail = ProjectBriefSerializer(source='project', read_only=True)
    depends_on_detail = ProjectBriefSerializer(source='depends_on', read_only=True)
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)
    via_label = serializers.CharField(source='get_via_display', read_only=True)
    environment_name = serializers.CharField(source='environment.name', read_only=True, default=None)

    class Meta:
        model = Dependency
        fields = ['id', 'project', 'project_detail', 'depends_on', 'depends_on_detail', 'kind',
                  'kind_label', 'via', 'via_label', 'version', 'reference', 'environment',
                  'environment_name', 'notes']
        # Uniqueness is checked in validate(), with a message that names the environment.
        validators = []

    def validate(self, attrs):
        get = lambda name: attrs.get(name, getattr(self.instance, name, None))
        project, depends_on, environment = get('project'), get('depends_on'), get('environment')
        if project and project == depends_on:
            raise serializers.ValidationError('A project cannot depend on itself.')
        if environment and environment.project_id != project.id:
            raise serializers.ValidationError({'environment': 'That environment belongs to another project.'})
        others = Dependency.objects.filter(project=project, depends_on=depends_on, environment=environment)
        if self.instance:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            where = f' for {environment.name}' if environment else ''
            raise serializers.ValidationError(f'This dependency is already recorded{where}.')
        return attrs


class ServiceBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id', 'slug', 'name', 'kind', 'url']


class ProjectDetailSerializer(ProjectSerializer):
    dependencies = DependencySerializer(many=True, read_only=True)
    dependents = DependencySerializer(many=True, read_only=True)
    services = ServiceBriefSerializer(many=True, read_only=True)
    links = LinkSerializer(many=True, read_only=True)

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + ['dependencies', 'dependents', 'services', 'links']


class PlatformSerializer(AutoSlugMixin, serializers.ModelSerializer):
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)
    links = LinkSerializer(many=True, read_only=True)
    environment_count = serializers.IntegerField(source='environments.count', read_only=True)

    class Meta:
        model = Platform
        fields = ['id', 'slug', 'name', 'kind', 'kind_label', 'provider', 'location', 'public_ips',
                  'dynamic_dns', 'hostnames', 'os', 'notes', 'cleanup_notes', 'links',
                  'environment_count']

    def validate_public_ips(self, value):
        # Addresses, or networks for a CDN in front (the health checks' DNS comparison).
        entries = _string_list(value)
        for entry in entries:
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError:
                raise serializers.ValidationError(f'"{entry}" is not an IP address or a network (like 198.51.100.0/24).')
        return entries

    def validate_hostnames(self, value):
        return _string_list(value)


class PlatformDetailSerializer(PlatformSerializer):
    environments = EnvironmentWithProjectSerializer(many=True, read_only=True)

    class Meta(PlatformSerializer.Meta):
        fields = PlatformSerializer.Meta.fields + ['environments']


class RepositorySerializer(AutoSlugMixin, serializers.ModelSerializer):
    hosting_label = serializers.CharField(source='get_hosting_display', read_only=True)
    project_details = ProjectBriefSerializer(source='projects', many=True, read_only=True)

    class Meta:
        model = Repository
        fields = ['id', 'slug', 'name', 'hosting', 'hosting_label', 'remote_url', 'local_path',
                  'private', 'projects', 'project_details', 'notes', 'github_id', 'github_url',
                  'github_description', 'default_branch', 'language', 'topics', 'archived', 'fork',
                  'pushed_at', 'open_issues', 'synced_at', 'github_missing']
        read_only_fields = ['github_id', 'github_url', 'github_description', 'default_branch',
                            'language', 'topics', 'archived', 'fork', 'pushed_at', 'open_issues',
                            'synced_at', 'github_missing']


class ServiceSerializer(AutoSlugMixin, serializers.ModelSerializer):
    project_details = ProjectBriefSerializer(source='projects', many=True, read_only=True)

    class Meta:
        model = Service
        fields = ['id', 'slug', 'name', 'kind', 'url', 'account', 'notes', 'projects', 'project_details']


def _string_list(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise serializers.ValidationError('A list of strings is expected.')
    return [v.strip() for v in value if v.strip()]
