""""Needs attention": everything the gateway knows is wrong, most serious first.

Built here rather than in the browser, so any other reader of the API (a future MCP, an
alert) gets the same list. Each item has a stable `key` (the same problem keeps the same
key from one run to the next): notifications use it to announce a problem once when it
appears and once when it clears.
"""
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

from backups.attention import attention as backups_attention
from domains.attention import attention as domains_attention
from catalog.models import GitHubProfile, Platform, Repository
from . import local
from .checks import CERT_INVALID
from .models import MonitorState, UrlCheck

TLS_WARN = timedelta(days=21)        # Let's Encrypt renews at 30 days left: under 21, renewal is failing
TOKEN_WARN = timedelta(days=14)
SEVERITY_ORDER = {'danger': 0, 'warning': 1, 'info': 2}


def _ref(obj):
    return {'slug': obj.slug, 'name': obj.name} if obj else None


def _local(dt, fmt='%d %b %H:%M'):
    return timezone.localtime(dt).strftime(fmt)


def items(now=None):
    now = now or timezone.now()
    out = []

    def add(key, kind, severity, title, detail='', project=None, platform=None, page=None):
        out.append({'key': key, 'kind': kind, 'severity': severity, 'title': title, 'detail': detail,
                    'project': _ref(project), 'platform': _ref(platform), 'page': page})

    # The checks themselves: a stopped worker would otherwise look like "all fine".
    state = MonitorState.get()
    stale_after = timedelta(minutes=settings.HEALTH_CHECK_MINUTES * 4)
    if not state.checks_ran_at:
        add('worker:never', 'worker', 'warning', 'The health checks have not run yet',
            f'The worker runs them every {settings.HEALTH_CHECK_MINUTES:g} minutes.', page='status')
    elif now - state.checks_ran_at > stale_after:
        add('worker:stopped', 'worker', 'danger', 'The health checks have stopped',
            f'Last run {_local(state.checks_ran_at)}. Is the worker container running?', page='status')
    elif state.checks_offline:
        add('worker:offline', 'worker', 'warning', 'The gateway was offline at the last check',
            'Nothing answered, so the results shown are from the run before.', page='status')

    # Sites. One certificate or DNS warning per host, even when several URLs share it.
    tls_hosts, renew_hosts, dns_hosts = set(), set(), set()
    checks = UrlCheck.objects.select_related('environment__project', 'environment__platform')
    for c in checks:
        env, project = c.environment, c.environment.project
        host = urlsplit(c.url).hostname or c.url
        where = f'{project.name}  ·  {env.name}'
        if c.state == UrlCheck.State.DOWN:
            add(f'down:{env.id}:{c.url}', 'down', 'danger', f'Down: {host}',
                f'{where}: {c.error}, since {_local(c.since)}', project=project)
            continue
        if host not in tls_hosts:
            if c.tls_expires_at and c.tls_expires_at - now < TLS_WARN:
                tls_hosts.add(host)
                days = (c.tls_expires_at - now).days
                add(f'tls:{host}', 'tls', 'danger' if days < 7 else 'warning', f'Certificate expires: {host}',
                    f'{where}: on {_local(c.tls_expires_at, "%d %b %Y")} ({days} days left)', project=project)
            elif c.tls_error.startswith(CERT_INVALID):
                # Up, but every visitor's browser stops at a warning first.
                tls_hosts.add(host)
                add(f'tls-invalid:{host}', 'tls', 'danger', f'Certificate not valid: {host}',
                    f'{where}: the site answers, but browsers show a warning. {c.tls_error}', project=project)
            elif c.tls_error:
                tls_hosts.add(host)
                add(f'tls-error:{host}', 'tls', 'warning', f'Certificate problem: {host}',
                    f'{where}: {c.tls_error}', project=project)
        if c.tls_elsewhere and host not in renew_hosts:
            renew_hosts.add(host)
            names = ', '.join(c.tls_elsewhere)
            platform = env.platform.name if env.platform else 'this server'
            expiry = f' It expires on {_local(c.tls_expires_at, "%d %b %Y")}.' if c.tls_expires_at else ''
            add(f'tls-renew:{host}', 'tls', 'warning', f'Certificate can’t renew: {host}',
                f'{where}: its certificate also covers {names}, which point away from {platform}, '
                f'so certbot there can’t prove them. Give these sites a certificate of their own.{expiry}',
                project=project, platform=env.platform)
        if c.dns_match is False and host not in dns_hosts:
            dns_hosts.add(host)
            add(f'dns:{host}', 'dns', 'warning', f'Points elsewhere: {host}',
                f'{where}: resolves to {", ".join(c.ips)}, which isn’t {env.platform.name if env.platform else "its platform"}',
                project=project, platform=env.platform)

    # The backup planner: jobs, agents, targets.
    backups_attention(add, now)

    # Domains: expiring, expired, no date.
    domains_attention(add, timezone.localdate(now))

    # The gateway's host itself: git repos, nginx sites, systemd services (the local scan).
    local.attention(add, now)

    # GitHub.
    profile = GitHubProfile.objects.first()
    if settings.GITHUB_TOKEN and profile and profile.token_expires_at and profile.token_expires_at - now < TOKEN_WARN:
        expired = profile.token_expires_at < now
        add('github:token', 'github', 'danger' if expired else 'warning',
            'The GitHub token has expired' if expired else 'The GitHub token expires soon',
            f'On {_local(profile.token_expires_at, "%d %b %Y")}: create a new one and update .env.',
            page='repositories')
    if profile and profile.last_error:
        add('github:sync', 'github', 'warning', 'The last GitHub sync failed', profile.last_error, page='repositories')
    unlinked = Repository.objects.filter(github_id__isnull=False, archived=False, projects__isnull=True).count()
    missing = Repository.objects.filter(github_missing=True).count()
    if unlinked or missing:
        parts = ([f'{unlinked} with no project'] if unlinked else []) + ([f'{missing} not found on GitHub'] if missing else [])
        add('github:repos', 'github', 'info', 'Repositories to sort out', ', '.join(parts), page='repositories')

    # Cleanup notes on platforms: work still to do.
    for platform in Platform.objects.exclude(cleanup_notes=''):
        first = platform.cleanup_notes.strip().splitlines()[0]
        add(f'cleanup:{platform.slug}', 'cleanup', 'info', f'Cleanup on {platform.name}', first[:200], platform=platform)

    out.sort(key=lambda item: SEVERITY_ORDER[item['severity']])
    return out
