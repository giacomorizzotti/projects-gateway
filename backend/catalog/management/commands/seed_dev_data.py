"""Fill the dev database with invented data, so the dev server never holds the real catalog.

    ../venv/bin/python manage.py seed_dev_data [--user USERNAME]

Everything in the dev database is replaced by seed/demo.yaml (through import_inventory) plus
live status made up around it: health checks (one site down, one failing, one certificate
about to expire), the host scan (repos with changes or unpushed commits, nginx sites, a failed
unit), domains near their expiry, backup jobs and runs (one failed). Every page and kind of
"needs attention" item has something to show, and nothing comes from the real catalog.

The logins are kept (the users already in the dev database), so you can still sign in; on a
new database, --user adds yours (your auth-server username). The project groups, technology
categories, platform kinds and repository hostings are the defaults the migrations create.

It refuses to run without DEBUG (production's containers force it off) and when the settings
point at the live database (data/gateway.sqlite3). For a snapshot of the real catalog instead,
there's refresh_dev_db.
"""
import importlib
import os
import secrets
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from backups.models import BackupAgent, BackupJob, BackupRun, BackupTarget, JobTarget
from catalog.management.commands.refresh_dev_db import dev_database
from catalog.models import Client, Environment, Platform, Project, Repository, Service
from domains.models import Domain
from monitoring.models import CheckEvent, LocalScan, MonitorState, UrlCheck

DEMO = settings.REPO_DIR / 'seed' / 'demo.yaml'
# The demo's home server: after the import it takes the slug the host scan describes
# (SCAN_PLATFORM), whatever .env sets it to, so the made-up scan lands on it.
DEMO_HOME = 'home-server'

# Where each platform answers (the documentation ranges, as in demo.yaml).
PLATFORM_IPS = {DEMO_HOME: ['203.0.113.10'], 'cloud-vps': ['198.51.100.20'], 'shared-hosting': ['192.0.2.44']}
DOWN = 'https://status.home.example/'                 # down since this morning
FAILING = 'https://test.shop.acme.example/'           # failed once, to be confirmed
TLS_SOON = 'https://www.northwind.example/'           # certificate not renewing


class Command(BaseCommand):
    help = 'Replace the dev database with invented data (seed/demo.yaml plus made-up live status).'

    def add_arguments(self, parser):
        parser.add_argument('--user', action='append', default=[],
                            help='An auth-server username to let in (repeatable). The users already '
                                 'in the dev database are kept anyway.')

    def handle(self, *args, user, **options):
        target = dev_database()
        live = settings.REPO_DIR / 'data' / 'gateway.sqlite3'
        if not settings.DEBUG:
            raise CommandError('DEBUG is off: this looks like production. The dev server runs with '
                               'DJANGO_DEBUG=True.')
        if os.path.realpath(target) == os.path.realpath(live):      # (no stat: data/ may be unreadable)
            raise CommandError(f'The settings point at the live database itself ({target}): '
                               'set DATA_DIR in .env to the dev folder (data/dev) first.')

        users = [(u.username, u.first_name, u.last_name) for u in User.objects.all()]
        users += [(name, '', '') for name in user if name not in {u[0] for u in users}]
        if not users:
            raise CommandError('No user would be able to sign in: add yours with --user <username>.')

        now = timezone.now()
        call_command('flush', interactive=False, verbosity=0)
        with transaction.atomic():
            self.defaults()
            for username, first, last in users:
                login = User(username=username, first_name=first, last_name=last)
                login.set_unusable_password()
                login.save()
            call_command('import_inventory', str(DEMO), verbosity=0)
            Platform.objects.filter(slug=DEMO_HOME).update(slug=settings.SCAN_PLATFORM)
            self.checks(now)
            self.scan(now)
            self.domains(now)
            self.backups(now)
        if options['verbosity']:
            self.stdout.write(self.style.SUCCESS(
                f'{target} now holds the demo catalog: {Project.objects.count()} projects, '
                f'{UrlCheck.objects.count()} checked URLs, {Domain.objects.count()} domains, '
                f'{BackupJob.objects.count()} backup jobs. Users: {", ".join(u[0] for u in users)}.'))

    def defaults(self):
        """The groups, categories, platform kinds and repository hostings a fresh database gets
        from its migrations (flush emptied them)."""
        importlib.import_module('catalog.migrations.0005_project_groups').create_groups(apps, None)
        importlib.import_module('catalog.migrations.0007_technology_categories').create_categories(apps, None)
        importlib.import_module('catalog.migrations.0008_platform_kinds').create_kinds(apps, None)
        importlib.import_module('catalog.migrations.0009_repository_hostings').create_hostings(apps, None)

    def checks(self, now):
        """A run that just finished: everything up for a week, but for a few."""
        environments = Environment.objects.select_related('project', 'platform').filter(checks_enabled=True)
        count = 0
        for env in environments:
            if env.project.status in (Project.Status.ARCHIVED, Project.Status.DISCONTINUED):
                continue
            slug = env.platform.slug if env.platform else ''
            ips = PLATFORM_IPS.get(DEMO_HOME if slug == settings.SCAN_PLATFORM else slug, [])
            for i, url in enumerate(env.urls):
                if 'localhost' in url:
                    continue
                check = UrlCheck(environment=env, url=url, state=UrlCheck.State.UP, since=now - timedelta(days=7),
                                 checked_at=now, status_code=200, response_ms=180 + 37 * count, final_url=url,
                                 ips=ips, dns_match=True, tls_expires_at=now + timedelta(days=60 + count),
                                 tls_names=[url.split('/')[2]])
                if url == DOWN:
                    check.state, check.since, check.status_code, check.response_ms = (
                        UrlCheck.State.DOWN, now - timedelta(hours=3), None, None)
                    check.error, check.attempts = 'Timed out connecting', 3
                    CheckEvent.objects.create(environment=env, url=url, at=check.since, state=UrlCheck.State.DOWN,
                                              detail='Timed out connecting')
                    CheckEvent.objects.create(environment=env, url=url, at=now - timedelta(days=2),
                                              state=UrlCheck.State.UP, detail='200')
                elif url == FAILING:
                    check.failing_since, check.status_code, check.error = now - timedelta(minutes=2), None, 'Connection refused'
                elif url == TLS_SOON:
                    check.tls_expires_at = now + timedelta(days=9)
                check.save()
                count += 1
        state = MonitorState.get()
        state.checks_ran_at, state.checks_seconds, state.checks_count = now, 4.2, count
        state.save()

    def scan(self, now):
        """The host scan, as deploy/scan_local.py would write it on the home server."""
        def repo(slug, **extra):
            r = Repository.objects.get(slug=slug)
            out = {'path': r.local_path, 'branch': 'main', 'ahead': 0, 'behind': 0, 'changes': 0, 'untracked': 0,
                   'remotes': {'origin': r.remote_url} if r.remote_url else {},
                   'head': secrets.token_hex(4)[:7], 'date': (now - timedelta(days=3)).isoformat(),
                   'subject': 'Small fixes'}
            if r.remote_url:
                out['upstream'] = 'origin/main'
            out.update(extra)
            return out

        def site(file, *names, here=True):
            return {'file': file, 'names': [{'name': n, 'ips': ['203.0.113.10'], 'here': here} for n in names],
                    'ssl_certificates': [f'/etc/letsencrypt/live/{names[0]}/fullchain.pem'], 'proxy_pass': [], 'roots': []}

        data = {
            'version': 1,
            'host': settings.SCAN_PLATFORM,
            'scanned_at': now.isoformat(timespec='seconds'),
            'seconds': 1.3,
            'repos': [
                repo('demo-ui'),
                repo('rental-shop', changes=3, untracked=1),
                repo('northwind-site'),
                repo('status-board', ahead=2, subject='Printer list from the config file'),
                repo('old-blog'),
                {'path': '/home/projects/demo/experiments', 'branch': 'main', 'changes': 0, 'untracked': 4,
                 'remotes': {}, 'head': 'a1b2c3d', 'date': (now - timedelta(days=40)).isoformat(), 'subject': 'Try things'},
            ],
            'nginx': [
                site('test.shop.acme.example', 'test.shop.acme.example'),
                site('status.home.example', 'status.home.example'),
                site('dev.home.example', 'dev.home.example'),
                site('old.home.example', 'old.home.example'),          # in no project: a leftover?
            ],
            'systemd': {'failed': [{'unit': 'printer-sync.service', 'description': 'Printer list sync'}], 'running': 31},
        }
        scan = LocalScan.get()
        scan.data, scan.scanned_at, scan.read_at, scan.error = data, now, now, ''
        scan.save()

    def domains(self, now):
        """One per kind of expiry warning, the registrar and DNS linked to services."""
        today = timezone.localdate()
        registrar = Service.objects.get(slug='example-registrar')
        hosting = Service.objects.get(slug='example-hosting')
        for name, days, auto, client, notes in [
            ('acme.example', 210, True, 'Acme Rentals', ''),
            ('northwind.example', 20, False, 'Northwind Bakery', 'Renewed by hand: ask the bakery first.'),
            ('home.example', 4, False, None, 'The dynamic DNS name.'),
            ('demo-ui.example', None, False, None, 'The registry publishes no expiry: type it.'),
        ]:
            domain = Domain.objects.create(
                name=name, registrar='Example Registrar Inc.', dns_provider='Example Hosting',
                registrar_service=registrar, dns_service=hosting, auto_renew=auto,
                client=Client.objects.get(name=client) if client else None,
                expires_on=today + timedelta(days=days) if days is not None else None,
                registered_on=today - timedelta(days=700), nameservers=['ns1.hosting.example', 'ns2.hosting.example'],
                registry_status=['client transfer prohibited'], looked_up_at=now - timedelta(hours=5),
                lookup_error='' if days is not None else 'This registry publishes no expiry date: enter it by hand.',
                notes=notes)
            if name == 'demo-ui.example':
                domain.projects.add(Project.objects.get(slug='demo-ui'))

    def backups(self, now):
        """The home server's agent, a disk, three jobs: two fine, one whose last run failed."""
        home = Platform.objects.get(slug=settings.SCAN_PLATFORM)
        BackupAgent.objects.create(platform=home, token_hash=secrets.token_hex(32), last_seen_at=now - timedelta(minutes=4),
                                   version='1', hostname=settings.SCAN_PLATFORM)
        disk = BackupTarget.objects.create(platform=home, name='Backup disk', path='/mnt/backup', mount='/mnt/backup',
                                           location=BackupTarget.Location.HOME, keep=14)
        for slug, name, project, kind, source, frequency, hour, fail in [
            ('shop-test-db', 'Rental shop TEST database', 'rental-shop', BackupJob.Kind.MYSQL, 'rental_shop_test', BackupJob.Frequency.DAILY, 2, False),
            ('status-board-db', 'Status board database', 'status-board', BackupJob.Kind.SQLITE, '/home/projects/demo/status-board/db.sqlite3', BackupJob.Frequency.DAILY, 3, True),
            ('demo-code', 'Demo projects (whole folder)', None, BackupJob.Kind.FILES, '/home/projects/demo/', BackupJob.Frequency.WEEKLY, 4, False),
        ]:
            job = BackupJob.objects.create(
                name=name, slug=slug, project=Project.objects.filter(slug=project).first(), platform=home, kind=kind,
                source=source, folder=slug.replace('-', '_'), prefix=slug, frequency=frequency, hour=hour,
                excludes=['*/node_modules/*', '*/venv/*'] if kind == BackupJob.Kind.FILES else [])
            JobTarget.objects.create(job=job, target=disk)
            for days_ago in (3, 2, 1):
                started = timezone.localtime(now - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=5)
                failed = fail and days_ago == 1
                BackupRun.objects.create(
                    job=job, started_at=started, finished_at=started + timedelta(seconds=12),
                    status=BackupRun.Status.FAILED if failed else BackupRun.Status.OK,
                    size=None if failed else 4_200_000 + 1000 * days_ago,
                    files=[] if failed else [{'target': disk.id, 'path': f'/mnt/backup/{job.folder}/{slug}_{started:%Y%m%d}.gz',
                                              'ok': True, 'error': ''}],
                    error='database is locked' if failed else '')
