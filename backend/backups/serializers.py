import re

from rest_framework import serializers

from catalog.serializers import AutoSlugMixin, PlatformBriefSerializer, ProjectBriefSerializer
from .models import BackupJob, BackupRun, BackupTarget, JobTarget

# Re-creatable folders, left out of every zip unless the job says otherwise.
DEFAULT_EXCLUDES = ['*/node_modules/*', '*/venv/*', '*/venv-*/*', '*/.venv/*']

# The agent checks these again on its side: nothing here can become a command-line option
# or a path outside its allowed roots.
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
DATABASE = re.compile(r'^[A-Za-z0-9_$][A-Za-z0-9_$-]*$')


class BackupTargetSerializer(serializers.ModelSerializer):
    platform_detail = PlatformBriefSerializer(source='platform', read_only=True)
    location_label = serializers.CharField(source='get_location_display', read_only=True)

    class Meta:
        model = BackupTarget
        fields = ['id', 'platform', 'platform_detail', 'name', 'path', 'mount', 'location', 'location_label',
                  'keep', 'notes']

    def validate_path(self, value):
        if not value.startswith('/') or '..' in value.split('/'):
            raise serializers.ValidationError('An absolute path, without "..".')
        return value.rstrip('/') or '/'

    def validate_mount(self, value):
        if value and (not value.startswith('/') or '..' in value.split('/')):
            raise serializers.ValidationError('An absolute path, without "..".')
        return value.rstrip('/')


class TargetBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupTarget
        fields = ['id', 'name', 'path', 'location']


class BackupJobSerializer(AutoSlugMixin, serializers.ModelSerializer):
    project_detail = ProjectBriefSerializer(source='project', read_only=True)
    platform_detail = PlatformBriefSerializer(source='platform', read_only=True)
    environment_name = serializers.CharField(source='environment.name', read_only=True, default=None)
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)
    frequency_label = serializers.CharField(source='get_frequency_display', read_only=True)
    # Ordered: the backup is made in the first, then copied to the others.
    target_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    targets = serializers.SerializerMethodField()

    class Meta:
        model = BackupJob
        fields = ['id', 'name', 'slug', 'project', 'project_detail', 'environment', 'environment_name',
                  'platform', 'platform_detail', 'kind', 'kind_label', 'source', 'credentials', 'excludes',
                  'folder', 'prefix', 'frequency', 'frequency_label', 'hour', 'target_ids', 'targets',
                  'enabled', 'requested_at', 'notes', 'created_at']
        read_only_fields = ['requested_at', 'created_at']
        # Both default to the slug (see validate).
        extra_kwargs = {'folder': {'required': False, 'allow_blank': True},
                        'prefix': {'required': False, 'allow_blank': True}}

    def get_targets(self, obj):
        return TargetBriefSerializer([jt.target for jt in obj.job_targets.all()], many=True).data

    def validate(self, attrs):
        attrs = super().validate(attrs)
        get = lambda name, default=None: attrs.get(name, getattr(self.instance, name, default))
        kind, source = get('kind'), (get('source') or '').strip()
        errors = {}
        if kind == BackupJob.Kind.MYSQL:
            if not DATABASE.match(source):
                errors['source'] = 'The database name: letters, digits, _ $ -.'
            if not NAME.match(get('credentials') or ''):
                errors['credentials'] = 'The option file in the agent’s credentials folder, e.g. shop.cnf.'
        else:
            if not source.startswith('/') or '..' in source.split('/'):
                errors['source'] = 'An absolute path, without "..".'
        excludes = get('excludes') or []
        if not isinstance(excludes, list) or not all(isinstance(e, str) and e and not e.startswith('-') for e in excludes):
            errors['excludes'] = 'A list of zip patterns, none starting with "-".'
        slug = attrs.get('slug') or (self.instance.slug if self.instance else '')
        folder = (get('folder') or slug).strip('/')
        prefix = get('prefix') or slug
        if not folder or not all(NAME.match(part) for part in folder.split('/')):
            errors['folder'] = 'A relative folder: letters, digits, . _ - and /.'
        if not NAME.match(prefix or ''):
            errors['prefix'] = 'Letters, digits, . _ -.'
        hour = get('hour', 0)
        if hour is None or not 0 <= hour <= 23:
            errors['hour'] = '0 to 23.'
        platform = get('platform')
        target_ids = attrs.get('target_ids')
        if target_ids is not None:
            found = {t.id: t for t in BackupTarget.objects.filter(pk__in=target_ids)}
            if not target_ids or len(found) != len(set(target_ids)):
                errors['target_ids'] = 'At least one target.'
            elif platform and any(t.platform_id != platform.id for t in found.values()):
                errors['target_ids'] = 'Targets on the job’s own platform only: its agent writes them.'
        elif self.instance is None:
            errors['target_ids'] = 'At least one target.'
        if errors:
            raise serializers.ValidationError(errors)
        attrs['source'], attrs['folder'], attrs['prefix'] = source, folder, prefix
        return attrs

    def _save_targets(self, job, target_ids):
        if target_ids is None:
            return
        job.job_targets.all().delete()
        JobTarget.objects.bulk_create(JobTarget(job=job, target_id=t, position=i) for i, t in enumerate(target_ids))

    def create(self, validated_data):
        target_ids = validated_data.pop('target_ids', None)
        validated_data.setdefault('excludes', DEFAULT_EXCLUDES if validated_data.get('kind') == BackupJob.Kind.FILES else [])
        job = super().create(validated_data)
        self._save_targets(job, target_ids)
        return job

    def update(self, instance, validated_data):
        target_ids = validated_data.pop('target_ids', None)
        job = super().update(instance, validated_data)
        self._save_targets(job, target_ids)
        return job


class BackupRunSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    job_name = serializers.CharField(source='job.name', read_only=True)

    class Meta:
        model = BackupRun
        fields = ['id', 'job', 'job_name', 'started_at', 'finished_at', 'status', 'status_label', 'size',
                  'sha256', 'files', 'error', 'requested']
