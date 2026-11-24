"""When a job is due, and what's wrong with the backups.

Schedules are simple: every day, week (Sunday), month (the 1st) or year (1 January), at
the job's hour, local time, like the old @daily/@weekly/@monthly/@yearly crontab lines.
A job is due when no run has started since its latest scheduled time, or when "Back up
now" was pressed after its latest run. A failed run isn't retried by itself: it's
reported (and notified), and "Back up now" runs it again.
"""
from datetime import timedelta

from django.utils import timezone

from .models import BackupJob, BackupRun

F = BackupJob.Frequency
GRACE = timedelta(hours=3)              # a scheduled run not started by then was missed
AGENT_SILENT = timedelta(hours=1)       # the agent checks in every 15 minutes
LOW_SPACE = 0.10                        # warn under 10% free…
LOW_SPACE_BYTES = 5 * 1024 ** 3         # …or under 5 GB


def _shift(at, frequency, steps):
    """`at` moved by `steps` periods of `frequency` (negative: back)."""
    if frequency == F.DAILY:
        return at + timedelta(days=steps)
    if frequency == F.WEEKLY:
        return at + timedelta(days=7 * steps)
    if frequency == F.MONTHLY:
        month = at.month - 1 + steps
        return at.replace(year=at.year + month // 12, month=month % 12 + 1)
    return at.replace(year=at.year + steps)


def last_slot(job, now=None):
    """The job's latest scheduled time at or before `now`."""
    local = timezone.localtime(now or timezone.now())
    at = local.replace(hour=job.hour, minute=0, second=0, microsecond=0)
    if job.frequency == F.WEEKLY:
        at -= timedelta(days=(at.weekday() - 6) % 7)        # back to Sunday
    elif job.frequency == F.MONTHLY:
        at = at.replace(day=1)
    elif job.frequency == F.YEARLY:
        at = at.replace(month=1, day=1)
    if at > local:
        at = _shift(at, job.frequency, -1)
    return at


def next_slot(job, now=None):
    return _shift(last_slot(job, now), job.frequency, 1)


def latest_run(job):
    return job.runs.order_by('-started_at', '-id').first()


def is_due(job, now=None, last=None):
    """(due, requested): whether the agent should run the job now, and whether by "Back up now".

    "Back up now" works on a job that isn't scheduled (`enabled` off) too: that's how a new
    job is tried before it's put on the schedule."""
    now = now or timezone.now()
    last = last if last is not None else latest_run(job)
    if job.requested_at and (last is None or last.started_at < job.requested_at):
        return True, True
    if not job.enabled:
        return False, False
    slot = last_slot(job, now)
    if last is None:
        return job.created_at < slot, False        # new: wait for the first scheduled time
    return last.started_at < slot, False


def job_problem(job, now=None, last=None):
    """What's wrong with a job: (severity, text), or None. An unscheduled job is never late,
    but a failed "Back up now" of it still shows."""
    now = now or timezone.now()
    last = last if last is not None else latest_run(job)
    if last and last.status == BackupRun.Status.FAILED:
        return 'danger', f'Failed on {timezone.localtime(last.started_at):%d %b %H:%M}: {last.error or "no reason given"}'
    if last and last.status == BackupRun.Status.PARTIAL:
        missing = [f['path'] for f in last.files if not f.get('ok')]
        return 'warning', f'Made, but not copied everywhere ({timezone.localtime(last.started_at):%d %b %H:%M}): ' + \
            ('; '.join(f.get('error') or f['path'] for f in last.files if not f.get('ok')) or ', '.join(missing))
    if not job.enabled:
        return None
    slot = last_slot(job, now)
    started_after_slot = last is not None and last.started_at >= slot
    if not started_after_slot and job.created_at < slot and now - slot > GRACE:
        when = f'{timezone.localtime(slot):%d %b %H:%M}'
        return 'danger', f'Missed: no run since its scheduled time, {when}'
    return None
