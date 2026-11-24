"""The API the backup agents call, with their own token ("Authorization: Agent <token>"),
never a user's login. An agent only ever sees its own platform's jobs and targets.

    POST /api/agent/checkin/   {version, hostname}       → the plan: targets, jobs, which are due
    POST /api/agent/runs/      one run's report           → 201
    POST /api/agent/report/    {disk, usage}              → 204
"""
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .models import BackupAgent, BackupJob, BackupRun
from .planning import is_due

KEYWORD = 'Agent'


class AgentAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header.startswith(f'{KEYWORD} '):
            return None
        token = header[len(KEYWORD) + 1:].strip()
        agent = BackupAgent.objects.select_related('platform').filter(token_hash=BackupAgent.hash(token)).first()
        if agent is None:
            raise AuthenticationFailed('Unknown agent token.')
        return None, agent

    def authenticate_header(self, request):
        return KEYWORD


class IsAgent(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, BackupAgent)


def agent_view(methods):
    def wrap(func):
        return api_view(methods)(authentication_classes([AgentAuthentication])(permission_classes([IsAgent])(func)))
    return wrap


def _target(t):
    return {'id': t.id, 'name': t.name, 'path': t.path, 'mount': t.mount, 'keep': t.keep}


@agent_view(['POST'])
def checkin(request):
    agent = request.auth
    agent.last_seen_at = timezone.now()
    agent.version = str(request.data.get('version', ''))[:20]
    agent.hostname = str(request.data.get('hostname', ''))[:100]
    agent.save(update_fields=['last_seen_at', 'version', 'hostname'])
    # All of them, scheduled or not: "Back up now" works on both, and the agent reports
    # what each one keeps in each target.
    jobs = BackupJob.objects.filter(platform=agent.platform).prefetch_related('job_targets__target')
    targets = {t.id: t for t in agent.platform.backup_targets.all()}
    out = []
    for job in jobs:
        due, requested = is_due(job, agent.last_seen_at)
        out.append({
            'id': job.id, 'slug': job.slug, 'name': job.name, 'kind': job.kind, 'source': job.source,
            'credentials': job.credentials, 'excludes': job.excludes, 'folder': job.folder,
            'prefix': job.prefix, 'targets': [jt.target_id for jt in job.job_targets.all()],
            'due': due, 'requested': requested,
        })
    return Response({'platform': agent.platform.slug, 'targets': [_target(t) for t in targets.values()], 'jobs': out})


class RunReport(serializers.Serializer):
    job = serializers.IntegerField()
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=BackupRun.Status.choices)
    size = serializers.IntegerField(required=False, allow_null=True)
    sha256 = serializers.CharField(required=False, allow_blank=True, max_length=64)
    files = serializers.ListField(child=serializers.DictField(), required=False)
    error = serializers.CharField(required=False, allow_blank=True)
    requested = serializers.BooleanField(required=False, default=False)


@agent_view(['POST'])
def report_run(request):
    data = RunReport(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    job = BackupJob.objects.filter(pk=v['job'], platform=request.auth.platform).first()
    if job is None:
        return Response({'detail': 'No such job on this platform.'}, status=404)
    files = [{'target': f.get('target'), 'path': str(f.get('path', ''))[:500], 'ok': bool(f.get('ok')),
              'error': str(f.get('error', ''))[:300]} for f in v.get('files', [])]
    run = BackupRun.objects.create(
        job=job, started_at=v['started_at'], finished_at=v['finished_at'], status=v['status'],
        size=v.get('size'), sha256=v.get('sha256', ''), files=files, error=v.get('error', '')[:2000],
        requested=v.get('requested', False))
    return Response({'id': run.id}, status=201)


@agent_view(['POST'])
def report(request):
    """Free space per target and what each job keeps there, after the agent's runs."""
    agent = request.auth
    disk, usage = request.data.get('disk'), request.data.get('usage')
    if isinstance(disk, dict):
        agent.disk = disk
    if isinstance(usage, dict):
        agent.usage = usage
    agent.last_seen_at = timezone.now()
    agent.save(update_fields=['disk', 'usage', 'last_seen_at'])
    return Response(status=204)
