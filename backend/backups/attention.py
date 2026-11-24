"""The backup planner's part of "Needs attention" (see monitoring/attention.py)."""
from django.utils import timezone

from catalog.models import Platform
from .models import BackupAgent, BackupJob, BackupRun, BackupTarget
from .planning import AGENT_SILENT, LOW_SPACE, LOW_SPACE_BYTES, job_problem


def _gb(n):
    return f'{n / 1024 ** 3:.1f} GB'


def attention(add, now=None):
    now = now or timezone.now()
    jobs = list(BackupJob.objects.select_related('project', 'platform'))
    last = {}
    for run in BackupRun.objects.filter(job__in=jobs).order_by('job_id', '-started_at', '-id'):
        last.setdefault(run.job_id, run)
    for job in jobs:
        problem = job_problem(job, now, last=last.get(job.id))
        if problem:
            add(f'backup-job:{job.id}', 'backup', problem[0], f'Backup: {job.name}', problem[1],
                project=job.project, page='backups')

    # The agents, on every platform with scheduled jobs.
    agents = {a.platform_id: a for a in BackupAgent.objects.all()}
    scheduled = Platform.objects.filter(backup_jobs__enabled=True).distinct()
    for platform in scheduled:
        agent = agents.get(platform.id)
        if agent is None or not agent.last_seen_at:
            add(f'agent:{platform.slug}', 'backup', 'warning', f'No backup agent on {platform.name} yet',
                'It has scheduled backup jobs, but its agent has never checked in.', platform=platform, page='backups')
        elif now - agent.last_seen_at > AGENT_SILENT:
            add(f'agent:{platform.slug}', 'backup', 'danger', f'The backup agent on {platform.name} has stopped',
                f'Last check-in {timezone.localtime(agent.last_seen_at):%d %b %H:%M}: is its crontab line still there?',
                platform=platform, page='backups')

    # Space on the targets, as their agents last saw it.
    for target in BackupTarget.objects.select_related('platform'):
        agent = agents.get(target.platform_id)
        disk = (agent.disk.get(str(target.id)) if agent else None) or {}
        if disk.get('error'):
            add(f'target:{target.id}', 'backup', 'warning', f'Backup target unavailable: {target.name}',
                f'{target.path} on {target.platform.name}: {disk["error"]}', platform=target.platform, page='backups')
        elif disk.get('total'):
            free, total = disk.get('free', 0), disk['total']
            if free < total * LOW_SPACE or free < LOW_SPACE_BYTES:
                add(f'target:{target.id}', 'backup', 'warning', f'Little space left: {target.name}',
                    f'{_gb(free)} free of {_gb(total)} on {target.path}', platform=target.platform, page='backups')

