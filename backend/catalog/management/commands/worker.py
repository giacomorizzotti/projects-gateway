"""The gateway's background jobs, in one long-running process (the `worker` container).

- Every HEALTH_CHECK_MINUTES (default 15), or within seconds of "Check now": the health
  checks of every public URL, then the notifications for what turned red or cleared.
- The host's local scan as soon as its cron job writes a new one (every 15
  minutes), then the notifications again.
- A URL that failed is checked again CONFIRM_AFTER later (5 minutes), with a few that are
  up: down, and notified, only if it still fails (monitoring/checks.py: confirm).
- The GitHub sync, every GITHUB_SYNC_HOURS (default 6).
- Each tracked domain looked up at its registry once a day (expiry, registrar, DNS).

"Due" is judged from the last run recorded in the database, so a restart doesn't trigger
an extra run. A tick is a few small SQLite reads.
"""
import logging
import os
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections, models
from django.utils import timezone

from catalog import github
from catalog.models import GitHubProfile
from monitoring import checks, local, notify
from monitoring.models import LocalScan, MonitorState
from domains import registry
from domains.models import Domain

log = logging.getLogger('gateway.worker')
TICK = 5


class Command(BaseCommand):
    help = 'Run the background jobs forever (or once, with --once).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run what is due, then exit.')

    def handle(self, *args, once=False, **options):
        github_every = timedelta(hours=float(os.environ.get('GITHUB_SYNC_HOURS', '6')))
        checks_every = timedelta(minutes=settings.HEALTH_CHECK_MINUTES)
        if not settings.GITHUB_TOKEN:
            log.warning('No GITHUB_TOKEN: the GitHub sync is off.')
        log.info('Worker started. Notifications: %s.', ', '.join(notify.channels()) or 'none configured')
        while True:
            close_old_connections()
            self.health_checks(checks_every)
            self.local_scan()
            self.confirm_failures()
            if settings.GITHUB_TOKEN:
                self.github_sync(github_every)
            self.domains_lookup()
            if once:
                return
            time.sleep(TICK)

    checks_attempted_at = None

    def health_checks(self, every):
        now = timezone.now()
        state = MonitorState.get()
        # The attempt too, not only the last saved run: a run that crashes after checking
        # mustn't be repeated at every tick.
        last = max(filter(None, [state.checks_ran_at, self.checks_attempted_at]), default=None)
        requested = state.check_requested_at and (last is None or state.check_requested_at > last)
        if last and now - last < every and not requested:
            return
        self.checks_attempted_at = now
        self.step('Health checks', checks.run, lambda r: (
            f'nothing answered ({r["checked"]} URLs): offline?' if r['offline']
            else f'{r["checked"]} URLs, {r["down"]} down, {r["failing"]} failing (to confirm).'))
        self.step('Notifications', notify.notify, lambda r: r and f'{r["subject"]} {r["results"]}')

    scan_mtime = None

    def local_scan(self):
        """The host's local scan, read as soon as a new one is written (a stat per tick), then
        what it turned red notified (a refused sudo, an unknown SSH key). Read with the checks,
        it lagged up to a whole run: the two 15-minute clocks drift apart, and on 2026-11-20 the
        worker read 10 seconds before each new file landed, so the page showed a 15-to-30-minute-old
        scan. A missing or unreadable file is read once, so the page says why; then again only
        when it changes."""
        try:
            mtime = settings.SCAN_FILE.stat().st_mtime
        except OSError:
            mtime = -1
        if mtime == self.scan_mtime:
            return
        self.scan_mtime = mtime
        self.step('Local scan', local.read, lambda r: None if r else LocalScan.get().error)
        self.step('Notifications', notify.notify, lambda r: r and f'{r["subject"]} {r["results"]}')

    confirm_attempted_at = None

    def confirm_failures(self, retry=timedelta(minutes=1)):
        """The failures due a second look, at most once a minute: a confirmation that found
        the gateway's own connection down is simply tried again."""
        now = timezone.now()
        if self.confirm_attempted_at and now - self.confirm_attempted_at < retry:
            return
        if not checks.confirmation_due(now).exists():
            return
        self.confirm_attempted_at = now
        self.step('Confirming failures', checks.confirm, lambda r: r and (
            f'nothing answered, not even the controls ({r["checked"]} URLs): offline? Trying again.'
            if r['offline'] else f'{r["checked"]} URLs, {r["down"]} down, {r["failing"]} still to confirm.'))
        self.step('Notifications', notify.notify, lambda r: r and f'{r["subject"]} {r["results"]}')

    def step(self, name, job, summary):
        try:
            message = summary(job())
            if message:
                log.info('%s: %s', name, message)
        except Exception:
            log.exception('%s crashed.', name)

    def domains_lookup(self, every=timedelta(days=1), per_tick=3):
        """A few domains per tick whose last lookup is a day old: spread out, never a burst."""
        cutoff = timezone.now() - every
        due = Domain.objects.filter(models.Q(looked_up_at__isnull=True) | models.Q(looked_up_at__lt=cutoff))
        for domain in due.order_by('looked_up_at')[:per_tick]:
            try:
                if not registry.refresh(domain):
                    log.info('Domain %s: %s', domain.name, domain.lookup_error)
            except Exception:
                log.exception('Looking up %s crashed.', domain.name)

    def github_sync(self, every):
        profile = GitHubProfile.objects.first()
        if profile and profile.attempted_at and timezone.now() - profile.attempted_at < every:
            return
        try:
            result = github.sync()
            log.info('GitHub sync: %(repos)s repos, %(created)s new, %(missing)s missing.', result)
        except github.GitHubError as e:
            log.error('GitHub sync failed: %s', e)
        except Exception:
            log.exception('GitHub sync crashed.')
