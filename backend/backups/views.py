from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from . import planning
from .models import BackupAgent, BackupJob, BackupRun, BackupTarget, JobTarget
from .serializers import DEFAULT_EXCLUDES, BackupJobSerializer, BackupRunSerializer, BackupTargetSerializer

RECENT_RUNS = 60


def _jobs():
    return (BackupJob.objects.select_related('project', 'platform', 'environment')
            .prefetch_related(Prefetch('job_targets', queryset=JobTarget.objects.select_related('target'))))


class BackupTargetViewSet(viewsets.ModelViewSet):
    queryset = BackupTarget.objects.select_related('platform')
    serializer_class = BackupTargetSerializer


class BackupJobViewSet(viewsets.ModelViewSet):
    serializer_class = BackupJobSerializer
    filterset_fields = ['project', 'platform', 'enabled']

    def get_queryset(self):
        return _jobs()

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        """"Back up now": the agent runs it at its next check-in (within 15 minutes)."""
        job = self.get_object()
        job.requested_at = timezone.now()
        job.save(update_fields=['requested_at'])
        return Response(self.get_serializer(job).data, status=202)


class BackupRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BackupRun.objects.select_related('job')
    serializer_class = BackupRunSerializer
    filterset_fields = ['job', 'status']


def _local(dt):
    return timezone.localtime(dt) if dt else None


@api_view(['GET'])
def overview(request):
    """The Backups page in one answer: agents, targets and their space, every job's state, recent runs."""
    now = timezone.now()
    agents = {a.platform_id: a for a in BackupAgent.objects.select_related('platform')}
    jobs = list(_jobs())
    last = {}
    last_ok = {}
    for run in BackupRun.objects.filter(job__in=jobs).order_by('job_id', '-started_at', '-id'):
        last.setdefault(run.job_id, run)
        if run.status == BackupRun.Status.OK:
            last_ok.setdefault(run.job_id, run)
    job_rows = []
    for job in jobs:
        latest = last.get(job.id)
        problem = planning.job_problem(job, now, last=latest)
        due, requested = planning.is_due(job, now, last=latest)
        agent = agents.get(job.platform_id)
        job_rows.append({
            **BackupJobSerializer(job).data,
            'last_run': BackupRunSerializer(latest).data if latest else None,
            'last_ok_at': last_ok[job.id].started_at if job.id in last_ok else None,
            'next_at': planning.next_slot(job, now) if job.enabled else None,
            'due': due,
            'waiting': bool(job.requested_at and (latest is None or latest.started_at < job.requested_at)),
            'problem': {'severity': problem[0], 'text': problem[1]} if problem else None,
            'usage': (agent.usage.get(str(job.id)) if agent else None) or {},
        })
    targets = []
    for target in BackupTarget.objects.select_related('platform'):
        agent = agents.get(target.platform_id)
        targets.append({**BackupTargetSerializer(target).data,
                        'disk': (agent.disk.get(str(target.id)) if agent else None)})
    runs = BackupRun.objects.select_related('job')[:RECENT_RUNS]
    return Response({
        'choices': {
            'kinds': [{'value': v, 'label': l} for v, l in BackupJob.Kind.choices],
            'frequencies': [{'value': v, 'label': l} for v, l in BackupJob.Frequency.choices],
            'locations': [{'value': v, 'label': l} for v, l in BackupTarget.Location.choices],
        },
        'default_excludes': DEFAULT_EXCLUDES,
        'agents': [{
            'platform': {'slug': a.platform.slug, 'name': a.platform.name},
            'last_seen_at': a.last_seen_at, 'version': a.version, 'hostname': a.hostname,
            'silent': bool(not a.last_seen_at or now - a.last_seen_at > planning.AGENT_SILENT),
        } for a in agents.values()],
        'targets': targets,
        'jobs': job_rows,
        'runs': BackupRunSerializer(runs, many=True).data,
    })
