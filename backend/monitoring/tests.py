import os
import socket
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock, skipUnless

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from catalog.models import Environment, Platform, PlatformKind, Project
from . import attention, checks, local, notify
from .models import CheckEvent, LocalScan, MonitorState, UrlCheck

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=dt_timezone.utc)


def up(**kw):
    return checks.Outcome(ok=True, status_code=200, response_ms=120, ips=['1.2.3.4'], **kw)


def down(error='Connection refused', **kw):
    return checks.Outcome(ok=False, error=error, ips=['1.2.3.4'], **kw)


class DescribeTests(TestCase):
    def test_short_reasons(self):
        name = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='x.it', port=443): Max retries exceeded with url: / "
            "(Caused by NameResolutionError(\"Failed to resolve 'x.it'\"))")
        self.assertEqual(checks.describe(name), 'The name does not resolve')
        expired = requests.exceptions.SSLError(
            "... [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1006)")
        self.assertEqual(checks.describe(expired), 'Certificate not valid: certificate has expired')
        self.assertEqual(checks.describe(requests.exceptions.ReadTimeout('x')), 'Timed out waiting for an answer')


class CheckUrlTests(TestCase):
    def test_a_failure_is_retried_before_it_counts(self):
        sleep = mock.Mock()
        with mock.patch.object(checks, 'lookup', return_value=(['1.2.3.4'], '')), \
             mock.patch.object(checks, 'fetch', side_effect=[down(), up()]), \
             mock.patch.object(checks, 'certificate', return_value=(NOW, '', ['x.it'])):
            outcome = checks.check_url('https://x.it/', sleep=sleep)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.attempts, 2)
        sleep.assert_called_once_with(checks.RETRY_WAIT)

    def test_up_means_any_answer_below_500(self):
        class Answer:
            def __init__(self, code):
                self.status_code, self.reason, self.url = code, 'Reason', 'https://x.it/'
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def iter_content(self, size):
                return iter([b'<html>'])

        for code, ok in [(200, True), (404, True), (401, True), (503, False)]:
            with mock.patch('requests.Session.get', return_value=Answer(code)) as get:
                outcome = checks.fetch('https://x.it/')
            self.assertEqual((outcome.ok, outcome.status_code), (ok, code))
            self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], checks.USER_AGENT)

    def test_an_invalid_certificate_is_not_an_outage(self):
        class Answer:
            status_code, reason, url = 200, 'OK', 'https://x.it/'
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def iter_content(self, size):
                return iter([b'<html>'])

        mismatch = requests.exceptions.SSLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not "
            "valid for 'x.it'. (_ssl.c:1006)")

        def get(url, verify=True, **kw):
            if verify:
                raise mismatch
            return Answer()

        with mock.patch('requests.Session.get', side_effect=get):
            outcome = checks.fetch('https://x.it/')
        self.assertEqual((outcome.ok, outcome.status_code), (True, 200))
        self.assertEqual(outcome.tls_error, 'Certificate not valid: it is for another name')
        with mock.patch('requests.Session.get', side_effect=mismatch):            # and nothing answers at all
            outcome = checks.fetch('https://x.it/')
        self.assertEqual((outcome.ok, outcome.error), (False, 'Certificate not valid: it is for another name'))

    def test_dns_is_compared_per_address_family_and_with_networks(self):
        cdn = checks.networks(['198.51.100.0/24', '2001:db8::/32', 'not an ip'])
        self.assertTrue(checks.dns_match(['198.51.100.150', '2001:db8:42::1'], cdn))
        self.assertTrue(checks.dns_match(['2001:db8:42::1'], cdn))       # the A answer was lost
        self.assertFalse(checks.dns_match(['8.8.8.8'], cdn))
        v4_only = checks.networks(['203.0.113.76'])
        self.assertIsNone(checks.dns_match(['2001:db8:4:1::76'], v4_only))  # IPv4 only: nothing to say
        self.assertIsNone(checks.dns_match(['1.2.3.4'], []))

    def test_a_name_that_never_resolves_is_down_after_every_attempt(self):
        with mock.patch.object(checks, 'lookup', return_value=([], checks.NO_NAME)), \
             mock.patch.object(checks, 'fetch') as fetch:
            outcome = checks.check_url('https://gone.example/', sleep=mock.Mock())
        self.assertEqual((outcome.ok, outcome.attempts), (False, checks.RETRIES + 1))
        self.assertEqual(outcome.error, 'The name does not resolve')
        fetch.assert_not_called()

    def test_a_failed_lookup_is_told_apart_from_a_name_that_does_not_exist(self):
        for errno, reason in [(socket.EAI_NONAME, checks.NO_NAME), (socket.EAI_AGAIN, checks.DNS_FAILED)]:
            with mock.patch('socket.getaddrinfo', side_effect=socket.gaierror(errno, 'x')):
                self.assertEqual(checks.lookup('x.it'), ([], reason))
        answer = [(socket.AF_INET6, 1, 6, '', ('2a00::1', 0, 0, 0)), (socket.AF_INET, 1, 6, '', ('1.2.3.4', 0))]
        with mock.patch('socket.getaddrinfo', return_value=answer):
            self.assertEqual(checks.lookup('x.it'), (['1.2.3.4', '2a00::1'], ''))


class RunTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(name='VPS', slug='vps', kind='vps', public_ips=['1.2.3.4'])
        cls.project = Project.objects.create(name='Site', slug='site', group='tools')
        cls.env = Environment.objects.create(project=cls.project, name='PROD', platform=cls.platform,
                                             urls=['https://a.example/', 'https://b.example/'])
        old = Project.objects.create(name='Old', slug='old', group='tools', status='archived')
        Environment.objects.create(project=old, name='PROD', urls=['https://old.example/'])
        internal = Project.objects.create(name='LAN', slug='lan', group='tools')
        Environment.objects.create(project=internal, name='DEV', urls=['http://10.0.0.5/'],
                                   checks_enabled=False)

    def run_with(self, results, now=NOW):
        with mock.patch.object(checks, 'resolve', return_value=[]):
            return checks.run(now=now, check=lambda url, **kw: results[url])

    def test_saves_one_row_per_url_and_skips_archived_and_disabled(self):
        result = self.run_with({'https://a.example/': up(), 'https://b.example/': up()})
        self.assertEqual(result, {'checked': 2, 'up': 2, 'down': 0, 'failing': 0, 'offline': False})
        self.assertEqual(set(UrlCheck.objects.values_list('url', flat=True)),
                         {'https://a.example/', 'https://b.example/'})
        self.assertTrue(all(c.dns_match for c in UrlCheck.objects.all()))
        self.assertEqual(MonitorState.get().checks_ran_at, NOW)

    def test_going_down_takes_a_failure_that_holds_up_and_coming_back_one_answer(self):
        self.run_with({'https://a.example/': up(), 'https://b.example/': up()})
        failed = NOW + timedelta(minutes=15)
        result = self.run_with({'https://a.example/': down(), 'https://b.example/': up()}, now=failed)
        self.assertEqual((result['down'], result['failing']), (0, 1))
        a = UrlCheck.objects.get(url='https://a.example/')
        self.assertEqual((a.state, a.failing_since, a.error), ('up', failed, 'Connection refused'))
        self.assertFalse(CheckEvent.objects.exists())

        self.run_with({'https://a.example/': down(), 'https://b.example/': up()}, now=failed + checks.CONFIRM_AFTER)
        a.refresh_from_db()
        self.assertEqual((a.state, a.since, a.failing_since), ('down', failed, None))     # down since the first failure
        back = failed + timedelta(minutes=15)
        self.run_with({'https://a.example/': up(), 'https://b.example/': up()}, now=back)
        self.assertEqual(list(CheckEvent.objects.values_list('url', 'state', 'at')),
                         [('https://a.example/', 'up', back), ('https://a.example/', 'down', failed)])

    def test_a_failure_that_does_not_hold_up_leaves_no_trace(self):
        self.run_with({'https://a.example/': up(), 'https://b.example/': up()})
        self.run_with({'https://a.example/': down(), 'https://b.example/': up()}, now=NOW + timedelta(minutes=15))
        # "Check now" a minute later: still failing, but too soon to tell.
        self.run_with({'https://a.example/': down(), 'https://b.example/': up()}, now=NOW + timedelta(minutes=16))
        self.assertEqual(UrlCheck.objects.get(url='https://a.example/').state, 'up')
        self.run_with({'https://a.example/': up(), 'https://b.example/': up()}, now=NOW + timedelta(minutes=30))
        a = UrlCheck.objects.get(url='https://a.example/')
        self.assertEqual((a.state, a.since, a.failing_since, a.error), ('up', NOW, None, ''))
        self.assertFalse(CheckEvent.objects.exists())

    def test_a_new_url_that_fails_is_not_down_before_it_is_confirmed(self):
        self.run_with({'https://a.example/': down(), 'https://b.example/': up()})
        a = UrlCheck.objects.get(url='https://a.example/')
        self.assertEqual((a.state, a.failing_since), ('up', NOW))
        self.assertFalse(CheckEvent.objects.exists())

    def test_a_run_where_nothing_answers_keeps_the_last_results(self):
        Environment.objects.create(project=self.project, name='DEV', urls=['https://c.example/'])
        everything = {u: up() for u in ['https://a.example/', 'https://b.example/', 'https://c.example/']}
        self.run_with(everything)
        result = self.run_with({u: down() for u in everything}, now=NOW + timedelta(minutes=5))
        self.assertTrue(result['offline'])
        self.assertFalse(UrlCheck.objects.filter(state='down').exists())
        self.assertTrue(MonitorState.get().checks_offline)

    def test_a_name_pointing_elsewhere_is_flagged(self):
        self.run_with({'https://a.example/': up(), 'https://b.example/': checks.Outcome(ok=True, ips=['9.9.9.9'])})
        self.assertFalse(UrlCheck.objects.get(url='https://b.example/').dns_match)

    def test_projects_in_a_hidden_group_are_not_checked(self):
        hidden = Project.objects.create(name='Shelved', slug='shelved', group='archive')
        Environment.objects.create(project=hidden, name='PROD', urls=['https://shelved.example/'])
        self.assertNotIn('https://shelved.example/', [url for _, url in checks.targets()])
        from catalog.models import ProjectGroup
        ProjectGroup.objects.filter(slug='archive').update(hidden=False)
        self.assertIn('https://shelved.example/', [url for _, url in checks.targets()])

    def test_urls_no_longer_in_the_catalog_are_dropped(self):
        self.run_with({'https://a.example/': up(), 'https://b.example/': up()})
        Environment.objects.filter(pk=self.env.pk).update(urls=['https://a.example/'])
        self.run_with({'https://a.example/': up()})
        self.assertEqual(list(UrlCheck.objects.values_list('url', flat=True)), ['https://a.example/'])


class ConfirmTests(TestCase):
    """a.example fails a regular run; `confirm` looks again, with b and c as controls."""

    @classmethod
    def setUpTestData(cls):
        vps = Platform.objects.create(name='VPS', slug='vps', kind='vps')
        other = Platform.objects.create(name='Shared', slug='shared', kind='shared_hosting')
        project = Project.objects.create(name='Site', slug='site', group='tools')
        Environment.objects.create(project=project, name='PROD', platform=vps,
                                   urls=['https://a.example/', 'https://b.example/'])
        Environment.objects.create(project=project, name='TEST', platform=other, urls=['https://c.example/'])
        Environment.objects.create(project=project, name='DEV', platform=other, urls=['https://d.example/'])

    def setUp(self):
        self.failed = NOW + timedelta(minutes=15)
        everything = {u: up() for u in self.urls()}
        self.go(checks.run, everything, NOW)
        self.go(checks.run, {**everything, 'https://a.example/': down()}, self.failed)

    def urls(self):
        return [f'https://{x}.example/' for x in 'abcd']

    def go(self, job, results, now):
        self.checked = []

        def check(url, **kw):
            self.checked.append(url)
            return results[url]
        with mock.patch.object(checks, 'resolve', return_value=[]):
            return job(now=now, check=check)

    def test_nothing_to_confirm_before_its_time(self):
        self.assertIsNone(self.go(checks.confirm, {}, self.failed + timedelta(minutes=4)))
        self.assertEqual(self.checked, [])

    def test_still_failing_while_the_controls_answer_is_down(self):
        later = self.failed + checks.CONFIRM_AFTER
        result = self.go(checks.confirm, {**{u: up() for u in self.urls()}, 'https://a.example/': down()}, later)
        # a, plus one control per platform: c or d (another platform first), then b.
        self.assertEqual(len(self.checked), 3)
        self.assertIn('https://b.example/', self.checked)
        self.assertEqual((result['down'], result['offline']), (1, False))
        a = UrlCheck.objects.get(url='https://a.example/')
        self.assertEqual((a.state, a.since, a.checked_at), ('down', self.failed, later))
        self.assertEqual(list(CheckEvent.objects.values_list('state', 'at')), [('down', self.failed)])
        # Not the regular run: its time and the other URLs are left alone.
        self.assertEqual(MonitorState.get().checks_ran_at, self.failed)
        self.assertEqual(UrlCheck.objects.count(), 4)

    def test_answering_again_clears_it(self):
        self.go(checks.confirm, {u: up() for u in self.urls()}, self.failed + checks.CONFIRM_AFTER)
        a = UrlCheck.objects.get(url='https://a.example/')
        self.assertEqual((a.state, a.failing_since), ('up', None))
        self.assertFalse(CheckEvent.objects.exists())

    def test_when_not_even_the_controls_answer_nothing_is_decided(self):
        later = self.failed + checks.CONFIRM_AFTER
        result = self.go(checks.confirm, {u: down() for u in self.urls()}, later)
        self.assertTrue(result['offline'])
        a = UrlCheck.objects.get(url='https://a.example/')
        self.assertEqual((a.state, a.failing_since, a.checked_at), ('up', self.failed, self.failed))
        self.assertFalse(UrlCheck.objects.filter(failing_since__isnull=False).exclude(pk=a.pk).exists())
        self.assertFalse(CheckEvent.objects.exists())
        self.assertFalse(MonitorState.get().checks_offline)


class AttentionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = Project.objects.create(name='Site', slug='site', group='tools')
        cls.env = Environment.objects.create(project=cls.project, name='PROD', urls=['https://a.example/'])
        # A fresh, empty local scan: it adds nothing of its own here (see LocalScanTests).
        LocalScan.objects.create(pk=1, scanned_at=NOW, data={'host': 'test'})

    def kinds(self, now=NOW):
        return [(i['kind'], i['severity']) for i in attention.items(now)]

    def test_a_worker_that_never_ran_or_stopped(self):
        self.assertIn(('worker', 'warning'), self.kinds())
        MonitorState.objects.update_or_create(pk=1, defaults={'checks_ran_at': NOW - timedelta(hours=2)})
        self.assertIn(('worker', 'danger'), self.kinds())

    def test_down_sites_and_expiring_certificates(self):
        MonitorState.objects.update_or_create(pk=1, defaults={'checks_ran_at': NOW})
        check = UrlCheck.objects.create(environment=self.env, url='https://a.example/', state='down',
                                        since=NOW, checked_at=NOW, error='Connection refused')
        self.assertEqual(self.kinds(), [('down', 'danger')])
        check.state, check.tls_expires_at = 'up', NOW + timedelta(days=10)
        check.save()
        self.assertEqual(self.kinds(), [('tls', 'warning')])
        check.tls_expires_at, check.tls_error = None, 'Certificate not valid: it is for another name'
        check.save()
        self.assertEqual(self.kinds(), [('tls', 'danger')])


class ApiTests(TestCase):
    def test_status_needs_login_and_has_every_part(self):
        self.assertEqual(APIClient().get('/api/status/').status_code, 401)
        api = APIClient()
        api.force_authenticate(User.objects.create(username='me'))
        data = api.get('/api/status/').json()
        self.assertEqual(set(data), {'monitor', 'attention', 'checks', 'events', 'local'})
        self.assertNotIn('notify_token', str(data['monitor']))


class CertificateNamesTests(RunTests):
    def test_names_on_the_certificate_that_point_elsewhere_are_kept(self):
        seen = {}

        def check(url, **kw):
            seen[url] = kw
            return up(tls_names=['a.example', 'api.example', 'alias.example'],
                      tls_name_ips={'api.example': ['9.9.9.9'], 'alias.example': ['1.2.3.4']})

        with mock.patch.object(checks, 'resolve', return_value=[]):
            checks.run(now=NOW, check=check)
        self.assertTrue(seen['https://a.example/']['cert_names'])        # a VPS renews its own
        a = UrlCheck.objects.get(url='https://a.example/')
        self.assertEqual(a.tls_elsewhere, ['api.example'])
        MonitorState.objects.filter(pk=1).update(checks_ran_at=NOW)
        renew = [i for i in attention.items(NOW) if i['key'] == 'tls-renew:a.example']
        self.assertEqual(len(renew), 1)
        self.assertIn('api.example', renew[0]['detail'])

    def test_shared_hosting_renews_its_own_certificates(self):
        Platform.objects.filter(pk=self.platform.pk).update(kind='shared_hosting')
        kinds = []
        with mock.patch.object(checks, 'resolve', return_value=[]):
            checks.run(now=NOW, check=lambda url, **kw: kinds.append(kw['cert_names']) or up())
        self.assertEqual(kinds, [False, False])

    def test_the_kinds_settings_say_where_certificates_are_renewed(self):
        def cert_names():
            seen = []
            with mock.patch.object(checks, 'resolve', return_value=[]):
                checks.run(now=NOW, check=lambda url, **kw: seen.append(kw['cert_names']) or up())
            return seen
        PlatformKind.objects.create(name='Dedicated server', slug='dedicated', renews_certificates=True)
        Platform.objects.filter(pk=self.platform.pk).update(kind='dedicated')
        self.assertEqual(cert_names(), [True, True])
        PlatformKind.objects.filter(slug='dedicated').update(renews_certificates=False)
        self.assertEqual(cert_names(), [False, False])

    def test_other_names_are_resolved_but_not_wildcards(self):
        with mock.patch.object(checks, 'lookup', return_value=(['1.2.3.4'], '')) as lookup, \
             mock.patch.object(checks, 'fetch', return_value=up()), \
             mock.patch.object(checks, 'certificate', return_value=(NOW, '', ['x.it', 'www.x.it', '*.x.it'])):
            outcome = checks.check_url('https://x.it/', cert_names=True)
        self.assertEqual(outcome.tls_name_ips, {'www.x.it': ['1.2.3.4']})
        self.assertEqual([c.args[0] for c in lookup.call_args_list], ['x.it', 'www.x.it'])


@override_settings(TELEGRAM_BOT_TOKEN='123:SECRET', TELEGRAM_CHAT_ID='42', EMAIL_HOST_USER='gw@example.com',
                   EMAIL_HOST_PASSWORD='pw', NOTIFY_EMAIL_TO=['me@example.com'],
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NotifyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        project = Project.objects.create(name='Site', slug='site', group='tools')
        cls.env = Environment.objects.create(project=project, name='PROD', urls=['https://a.example/'])

    def setUp(self):
        MonitorState.objects.update_or_create(pk=1, defaults={'checks_ran_at': NOW})
        LocalScan.objects.update_or_create(pk=1, defaults={'error': 'none in tests'})
        self.check = UrlCheck.objects.create(environment=self.env, url='https://a.example/', state='down',
                                             since=NOW, checked_at=NOW, error='Connection refused')
        answer = mock.Mock(ok=True, status_code=200)
        answer.json.return_value = {'ok': True, 'result': {}}
        patcher = mock.patch.object(notify.requests, 'post', return_value=answer)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_problem_is_announced_once_then_its_resolution(self):
        from django.core import mail
        sent = notify.notify(NOW)
        self.assertEqual(sent['results'], {'telegram': '', 'email': ''})
        self.assertIn('Down: a.example', self.post.call_args.kwargs['json']['text'])
        self.assertEqual(self.post.call_args.kwargs['json']['chat_id'], '42')
        self.assertEqual(mail.outbox[0].subject, 'Projects Gateway: 1 new problem')
        self.assertIsNone(notify.notify(NOW))                        # nothing new
        self.check.state = 'up'
        self.check.save()
        sent = notify.notify(NOW)
        self.assertEqual(sent['subject'], 'Projects Gateway: 1 resolved')
        self.assertEqual(MonitorState.get().notified, {})

    def test_a_failed_delivery_is_retried_and_never_shows_the_token(self):
        with override_settings(EMAIL_HOST_USER=''):
            self.post.side_effect = requests.exceptions.ConnectionError(
                'HTTPSConnectionPool: /bot123:SECRET/sendMessage (Caused by ...)')
            sent = notify.notify(NOW)
            self.assertNotIn('SECRET', sent['results']['telegram'])
            self.assertNotIn('SECRET', MonitorState.get().notify_error)
            self.assertEqual(MonitorState.get().notified, {})         # sent again next run
            self.post.side_effect = None
            self.assertIsNotNone(notify.notify(NOW))

    def test_nothing_without_a_channel(self):
        with override_settings(TELEGRAM_BOT_TOKEN='', EMAIL_HOST_USER=''):
            self.assertIsNone(notify.notify(NOW))
        self.post.assert_not_called()


SNAPSHOT = {
    'version': 1, 'host': 'home-server', 'scanned_at': '2026-11-12T11:50:00+00:00', 'seconds': 2.1,
    'repos': [
        {'path': '/home/projects/site', 'branch': 'main', 'upstream': 'origin/main', 'ahead': 2, 'behind': 0,
         'changes': 1, 'untracked': 0, 'remotes': {'origin': 'git@github.com:me/site.git'}, 'head': 'abc1234'},
        {'path': '/home/projects/stray', 'branch': 'master', 'changes': 0, 'untracked': 0, 'remotes': {}, 'head': 'def5678'},
    ],
    'nginx': [
        {'file': 'site', 'names': [{'name': 'a.example', 'ips': ['203.0.113.1']}]},
        {'file': 'old', 'names': [{'name': 'old.example', 'ips': ['9.9.9.9']}]},
        {'file': 'default', 'names': [{'name': '_', 'ips': []}]},
    ],
    'systemd': {'failed': [{'unit': 'old_gunicorn.service', 'description': 'gunicorn daemon'}], 'running': 40},
}

# NOW is 13:00 at +01:00.
SECURITY = {
    'auth_logs': ['/var/log/auth.log'], 'error': '',
    'sudo_failed': [
        {'at': '2026-11-10T08:00:00+01:00', 'user': 'deploy', 'command': '/usr/bin/id -u'},      # days ago
        {'at': '2026-11-12T08:30:21+01:00', 'user': 'deploy', 'command': '/usr/bin/id -u'},
        {'at': '2026-11-12T08:30:22+01:00', 'user': 'deploy', 'command': "/usr/bin/sh -c 'echo ZXhw'"},
    ],
    'ssh_logins': [
        {'at': '2026-11-12T09:00:00+01:00', 'method': 'publickey', 'user': 'deploy', 'ip': '1.2.3.4', 'key': 'SHA256:known'},
        {'at': '2026-11-12T10:00:00+01:00', 'method': 'password', 'user': 'alice', 'ip': '5.6.7.8', 'key': ''},
        {'at': '2026-11-12T11:00:00+01:00', 'method': 'publickey', 'user': 'root', 'ip': '9.9.9.9', 'key': 'SHA256:stranger'},
    ],
    'containers': [{'at': '2026-11-12T08:30:21+01:00', 'name': 'quirky_turing'}],
    'authorized_keys': [
        {'file': '/home/deploy/.ssh/authorized_keys', 'key': 'SHA256:known', 'comment': 'me@laptop'},
        {'file': '/root/.ssh/authorized_keys', 'key': 'SHA256:planted', 'comment': 'root@localhost'},
    ],
    'keys_watch': {'file': '/var/lib/projects-gateway-watch/authorized_keys', 'at': '2026-11-12T12:50:00+01:00', 'error': ''},
}


@override_settings(SCAN_PLATFORM='home-server')
class LocalScanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(name='home-server', slug='home-server', kind='home_server',
                                               public_ips=['203.0.113.1'])
        project = Project.objects.create(name='Site', slug='site', group='tools')
        Environment.objects.create(project=project, name='PROD', platform=cls.platform,
                                   urls=['https://a.example/', 'https://gone.example/', 'http://localhost:5180/'])
        from catalog.models import Repository
        Repository.objects.create(name='site', slug='site', local_path='/home/projects/site')
        Repository.objects.create(name='lost', slug='lost', local_path='/home/projects/lost')

    def read(self, snapshot=SNAPSHOT):
        import json
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'scan.json'
            path.write_text(json.dumps(snapshot))
            with mock.patch('monitoring.checks.resolve', return_value=[]):
                return local.read(path, now=NOW)

    def test_the_snapshot_is_compared_with_the_catalog(self):
        self.assertTrue(self.read())
        result = local.analyse()
        self.assertEqual([r['catalog'] and r['catalog']['slug'] for r in result['repos']], ['site', None])
        self.assertEqual([r['slug'] for r in result['missing_repos']], ['lost'])
        self.assertEqual([m['host'] for m in result['missing_sites']], ['gone.example'])
        names = {n['name']: n for site in result['nginx'] for n in site['names']}
        self.assertTrue(names['a.example']['here'])
        self.assertFalse(names['old.example']['here'])

    def test_what_it_adds_to_needs_attention(self):
        self.read()
        MonitorState.objects.update_or_create(pk=1, defaults={'checks_ran_at': NOW})
        keys = {i['key']: i['severity'] for i in attention.items(NOW)}
        self.assertEqual(keys['unit:old_gunicorn.service'], 'warning')
        self.assertEqual(keys['nginx-elsewhere:old'], 'warning')
        self.assertEqual(keys['nginx:missing'], 'warning')
        self.assertEqual(keys['git:missing'], 'warning')
        self.assertEqual((keys['git:unpushed'], keys['git:no-remote'], keys['git:unknown']), ('info', 'info', 'info'))
        self.assertNotIn('scan:stale', keys)
        self.assertIn('scan:stale', {i['key'] for i in attention.items(NOW + timedelta(hours=2))})

    def test_maldet_flagged_files_are_red_until_dealt_with(self):
        hit = {'at': '2026-11-12T06:28:01+01:00', 'pid': '7', 'report': '261112-0627.7', 'signature': '{HEX}php.cmdshell.r57.341',
               'file': '/home/projects/sites/wp/x.php', 'quarantined': False, 'ignored': False, 'exists': True}
        scans = [{'at': '2026-11-12T06:28:04+01:00', 'pid': '7', 'paths': '/home/projects/sites/wp/', 'files': 10,
                  'hits': 3, 'cleaned': 0, 'seconds': 3, 'report': '261112-0627.7'}]
        others = [{**hit, 'file': '/home/projects/sites/wp/deleted.php', 'exists': False},
                  {**hit, 'file': '/home/projects/sites/wp/false-positive.php', 'ignored': True}]
        self.read({**SNAPSHOT, 'maldet': {'log': '/x/event_log', 'scans': scans, 'hits': [hit, *others]}})
        items = {i['key']: i for i in attention.items(NOW)}
        item = items['maldet:hits:261112-0627.7']
        self.assertEqual(item['severity'], 'danger')
        self.assertEqual(item['title'], 'Malware on home-server: 1 file flagged by maldet')
        self.assertIn('x.php', item['detail'])
        self.assertNotIn('deleted.php', item['detail'])
        self.assertNotIn('false-positive.php', item['detail'])
        self.assertNotIn('maldet:stale', items)
        self.assertEqual(len(local.analyse()['maldet']['open_hits']), 1)

        # Deleted: the red item clears. Days without a scan: a warning.
        self.read({**SNAPSHOT, 'maldet': {'log': '/x/event_log', 'scans': scans, 'hits': [{**hit, 'exists': False}]}})
        keys = {i['key'] for i in attention.items(NOW + timedelta(days=3))}
        self.assertIn('maldet:stale', keys)
        self.assertNotIn('maldet:hits:261112-0627.7', keys)

    def test_without_maldet_nothing_about_it(self):
        self.read()
        self.assertIsNone(local.analyse()['maldet'])
        self.assertFalse([i for i in attention.items(NOW) if i['kind'] == 'malware'])

    @override_settings(SSH_KNOWN_KEYS=['SHA256:known'], SECURITY_SINCE=None)
    def test_security_events_are_red_for_a_day(self):
        self.read({**SNAPSHOT, 'security': SECURITY})
        items = {i['key']: i for i in attention.items(NOW) if i['kind'] == 'security'}
        sudo = items['security:sudo:deploy:2026-11-12T08:30:22+01:00']
        self.assertEqual((sudo['severity'], sudo['title']), ('danger', 'sudo refused on home-server: deploy, 2 times'))
        self.assertIn("sh -c 'echo ZXhw'", sudo['detail'])
        self.assertIn('quirky_turing', items['security:container:2026-11-12T08:30:21+01:00']['detail'])
        self.assertIn('alice from 5.6.7.8', items['security:ssh-password:2026-11-12T10:00:00+01:00']['detail'])
        self.assertIn('9.9.9.9', items['security:ssh-root:2026-11-12T11:00:00+01:00']['detail'])
        # Keys not in SSH_KNOWN_KEYS: one in a file, one only seen logging in.
        self.assertIn('/root/.ssh/authorized_keys (root@localhost)', items['security:ssh-key:SHA256:planted']['detail'])
        self.assertIn('login as root from 9.9.9.9', items['security:ssh-key:SHA256:stranger']['detail'])
        self.assertNotIn('security:ssh-key:SHA256:known', items)
        self.assertNotIn('security:keys-watch', items)

        # A day later the events are gone; the planted key isn't, and the watch has gone quiet.
        later = {i['key']: i['severity'] for i in attention.items(NOW + timedelta(hours=25)) if i['kind'] == 'security'}
        self.assertEqual(later, {'security:ssh-key:SHA256:planted': 'danger', 'security:keys-watch': 'warning'})

        # Events before SECURITY_SINCE are ignored.
        since = datetime(2026, 11, 12, 9, 30, tzinfo=dt_timezone.utc)
        with override_settings(SECURITY_SINCE=since):
            keys = {i['key'] for i in attention.items(NOW)}
        self.assertFalse([k for k in keys if k.startswith(('security:sudo:', 'security:container:'))])
        self.assertIn('security:ssh-root:2026-11-12T11:00:00+01:00', keys)

    @override_settings(SSH_KNOWN_KEYS=[])
    def test_without_a_key_list_the_keys_are_only_listed(self):
        self.read({**SNAPSHOT, 'security': {**SECURITY, 'keys_watch': {'file': '/x', 'at': None, 'error': 'missing'}}})
        items = {i['key']: i for i in attention.items(NOW) if i['kind'] == 'security'}
        self.assertFalse([k for k in items if k.startswith('security:ssh-key:')])
        self.assertEqual(items['security:ssh-keys-unlisted']['severity'], 'warning')
        self.assertIn('SHA256:planted', items['security:ssh-keys-unlisted']['detail'])
        self.assertEqual(items['security:keys-watch']['severity'], 'info')

    def test_without_security_traces_nothing_about_them(self):
        self.read()
        self.assertFalse([i for i in attention.items(NOW) if i['kind'] == 'security'])

    def test_a_missing_snapshot_is_reported(self):
        self.assertFalse(local.read(Path('/nonexistent/scan.json'), now=NOW))
        self.assertIn('crontab', LocalScan.get().error)


@override_settings(TELEGRAM_BOT_TOKEN='123:SECRET', TELEGRAM_CHAT_ID='42', EMAIL_HOST_USER='',
                   SSH_KNOWN_KEYS=['SHA256:known', 'SHA256:planted', 'SHA256:stranger'], SECURITY_SINCE=None)
class SecurityNotifyTests(TestCase):
    def setUp(self):
        MonitorState.objects.update_or_create(pk=1, defaults={'checks_ran_at': NOW})
        answer = mock.Mock(ok=True, status_code=200)
        answer.json.return_value = {'ok': True, 'result': {}}
        patcher = mock.patch.object(notify.requests, 'post', return_value=answer)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def scan(self, security):
        LocalScan.objects.update_or_create(pk=1, defaults={
            'data': {**SNAPSHOT, 'systemd': {}, 'security': security}, 'scanned_at': NOW, 'error': ''})

    def test_each_new_event_is_announced_and_ageing_out_is_not(self):
        self.scan(SECURITY)
        sent = notify.notify(NOW)
        self.assertIn('sudo refused on home-server: deploy, 2 times', self.post.call_args.kwargs['json']['text'])
        self.assertIsNone(notify.notify(NOW))                       # nothing new

        # Another refused sudo: a new key, announced; the one it replaces isn't "resolved".
        more = {'at': '2026-11-12T12:40:00+01:00', 'user': 'deploy', 'command': '/usr/bin/id -u'}
        self.scan({**SECURITY, 'sudo_failed': [*SECURITY['sudo_failed'], more]})
        sent = notify.notify(NOW)
        self.assertEqual(sent['subject'], 'Projects Gateway: 1 new problem')
        self.assertNotIn('Resolved', self.post.call_args.kwargs['json']['text'])

        # A day later every event has aged out: no message.
        MonitorState.objects.filter(pk=1).update(checks_ran_at=NOW + timedelta(hours=25))
        self.assertIsNone(notify.notify(NOW + timedelta(hours=25)))


SCRIPT = Path(__file__).resolve().parents[2] / 'deploy' / 'scan_local.py'


@skipUnless(SCRIPT.is_file(), 'deploy/ is not in the image')
class ScanScriptTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import importlib.util
        spec = importlib.util.spec_from_file_location('scan_local', SCRIPT)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def test_parsing(self):
        s = self.script
        self.assertEqual(s.strip_credentials('https://user:tok@github.com/me/x.git'), 'https://github.com/me/x.git')
        self.assertEqual(s.strip_credentials('git@github.com:me/x.git'), 'git@github.com:me/x.git')
        conf = 'server {\n  server_name a.example www.a.example;\n  ssl_certificate /x/fullchain.pem;\n' \
               '  ssl_certificate_key /x/privkey.pem;\n}'
        self.assertEqual(s.directive(conf, 'server_name'), [['a.example', 'www.a.example']])
        self.assertEqual(s.directive(conf, 'ssl_certificate'), [['/x/fullchain.pem']])

    def test_finds_repos_but_not_inside_skipped_folders(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for repo in ['a', 'a/nested', 'b/node_modules/dep', 'c/venv-x/lib']:
                (root / repo / '.git').mkdir(parents=True)
            self.assertEqual([p.relative_to(root).as_posix() for p in self.script.find_repos(root)], ['a', 'a/nested'])

    def test_maldet_log(self):
        s = self.script
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'logs').mkdir()
            (root / 'bad.php').write_text('x')
            (root / 'ignore_paths').write_text(f'/usr/local/maldetect\n{root}/fp\n')
            log = root / 'logs' / 'event_log'
            log.write_text(
                'Nov 01 2026 06:28:04 h maldet(1): {scan} scan completed on /var/www/: files 9, malware hits 0, cleaned hits 0, time 2s\n'
                'Nov 12 2026 06:27:57 h maldet(7): {scan} building file list for /var/www/, this might take awhile...\n'
                f'Nov 12 2026 06:28:01 h maldet(7): {{hit}} malware hit {{HEX}}php.cmdshell.r57.341 found for {root}/bad.php\n'
                f'Nov 12 2026 06:28:02 h maldet(7): {{hit}} malware hit {{HEX}}php.x.1 found for {root}/fp/a.php\n'
                f'Nov 12 2026 06:28:02 h maldet(7): {{hit}} malware hit {{HEX}}php.x.1 found for {root}/deleted.php\n'
                'Nov 12 2026 06:28:04 h maldet(7): {scan} scan completed on /var/www/: files 469, malware hits 3, cleaned hits 0, time 7s\n'
                'Nov 12 2026 06:28:04 h maldet(7): {scan} scan report saved, to view run: maldet --report 261112-0627.7\n'
                'not a maldet line\n')
            with mock.patch.object(s, 'MALDET', root):
                result = s.scan_maldet(log, now=datetime(2026, 11, 12, 12, 0).astimezone())
        # The scan of 1 November is older than MALDET_DAYS.
        self.assertEqual([(x['files'], x['hits'], x['report']) for x in result['scans']], [(469, 3, '261112-0627.7')])
        hits = {Path(h['file']).name: h for h in result['hits']}
        bad = hits['bad.php']
        self.assertEqual((bad['signature'], bad['exists'], bad['ignored'], bad['report']),
                         ('{HEX}php.cmdshell.r57.341', True, False, '261112-0627.7'))
        self.assertTrue(hits['a.php']['ignored'])
        self.assertFalse(hits['deleted.php']['exists'])
        self.assertIsNone(s.scan_maldet(Path('/nonexistent/event_log')))

    def test_security_traces(self):
        s = self.script
        import json
        # A throwaway key and its fingerprint as ssh-keygen -lf printed it.
        pub = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPiSmE0Y/J85lVFwzgJZg04035Cxfn4OtJlypdyqLduY test@example'
        self.assertEqual(s.key_fingerprint(f'no-pty,command="x" {pub}'),
                         ('SHA256:vcts8ZGUjrFJgbxKTMDl7VLMMDTBePyWQzls7k3F8U0', 'test@example'))
        self.assertEqual(s.key_fingerprint('ssh-rsa not-base64!'), (None, ''))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / 'auth.log'
            log.write_text(
                '2026-11-01T10:00:00.000000+01:00 h sudo: deploy : a password is required ; PWD=/x ; USER=root ; COMMAND=/usr/bin/id -u\n'
                '2026-11-12T08:30:21.299111+01:00 h sudo: deploy : a password is required ; PWD=/home/projects/app/frontend ; USER=root ; COMMAND=/usr/bin/id -u\n'
                '2026-11-12T08:30:22.000000+01:00 h sudo: deploy : (command continued) ZXhwb3J0\n'
                '2026-11-12T09:00:00.000000+01:00 h sudo:     alice : 3 incorrect password attempts ; TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/usr/bin/su\n'
                '2026-11-12T09:01:00.000000+01:00 h sudo: ci : user NOT in sudoers ; TTY=pts/1 ; PWD=/home/ci ; USER=root ; COMMAND=/usr/bin/ls\n'
                '2026-11-12T09:02:00.000000+01:00 h sudo: deploy : TTY=pts/0 ; PWD=/x ; USER=root ; COMMAND=/usr/bin/true\n'
                '2026-11-12T10:00:00.000000+01:00 h sshd[1]: Accepted publickey for deploy from 1.2.3.4 port 5 ssh2: ED25519 SHA256:+UI6abc/9\n'
                '2026-11-12T10:05:00.000000+01:00 h sshd-session[2]: Accepted password for alice from 5.6.7.8 port 6 ssh2\n'
                '2026-11-12T10:06:00.000000+01:00 h sshd[3]: Failed password for root from 198.51.100.7 port 7 ssh2\n'
                'not a log line\n')
            journal = '\n'.join([
                json.dumps({'__REALTIME_TIMESTAMP': '1794468621000000',
                            'MESSAGE': "level=info msg=\"sbJoin: gwep4 ''->'f4cd', gwep6 ''->''\" eid=f4cd ep=quirky_turing net=bridge"}),
                json.dumps({'__REALTIME_TIMESTAMP': '1794468700000000',
                            'MESSAGE': "level=info msg=\"sbJoin: gwep4 ''->'a1b2'\" eid=a1b2 ep=projects-gateway-app-1 net=x"}),
                json.dumps({'MESSAGE': 'sbJoin: ep=no_timestamp'}),
                'not json'])
            watch = root / 'watch'
            watch.write_text('/root/.ssh/authorized_keys 256 SHA256:planted/1 root@localhost (ED25519)\n')
            keys = root / 'authorized_keys'
            keys.write_text(f'# a comment\n{pub}\ncommand="x" ssh-rsa not-base64! bad\n')
            result = s.scan_security(now=datetime(2026, 11, 12, 12, 0).astimezone(), auth_logs=(root / 'gone', log),
                                     watch=watch, key_files=[keys, root / 'unreadable'], journal=lambda: journal)
            no_watch = s.scan_security(now=datetime(2026, 11, 12, 12, 0).astimezone(), auth_logs=(root / 'gone',),
                                       watch=root / 'gone', key_files=[], journal=lambda: '')
        self.assertEqual([(e['user'], e['command']) for e in result['sudo_failed']],
                         [('deploy', '/usr/bin/id -u'), ('alice', '/usr/bin/su'), ('ci', '/usr/bin/ls')])
        self.assertEqual([(e['method'], e['user'], e['ip'], e['key']) for e in result['ssh_logins']],
                         [('publickey', 'deploy', '1.2.3.4', 'SHA256:+UI6abc/9'), ('password', 'alice', '5.6.7.8', '')])
        self.assertEqual([c['name'] for c in result['containers']], ['quirky_turing'])
        self.assertEqual(result['containers'][0]['at'][:19],
                         datetime.fromisoformat('2026-11-12T08:30:21+01:00').astimezone().isoformat()[:19])
        self.assertEqual([(k['file'], k['key'], k['comment']) for k in result['authorized_keys']],
                         [('/root/.ssh/authorized_keys', 'SHA256:planted/1', 'root@localhost'),
                          (str(keys), 'SHA256:vcts8ZGUjrFJgbxKTMDl7VLMMDTBePyWQzls7k3F8U0', 'test@example')])
        self.assertEqual((result['error'], result['keys_watch']['error']), ('', ''))
        self.assertEqual((no_watch['error'], no_watch['keys_watch']['error']), ('no auth log found', 'missing'))


class CheckNowTests(TestCase):
    def test_check_now_asks_the_worker(self):
        api = APIClient()
        self.assertEqual(api.post('/api/status/check/').status_code, 401)
        api.force_authenticate(User.objects.create(username='me'))
        self.assertEqual(api.post('/api/status/check/').status_code, 202)
        self.assertIsNotNone(MonitorState.get().check_requested_at)


class WorkerLocalScanTests(TestCase):
    def test_read_as_soon_as_a_new_scan_lands(self):
        from catalog.management.commands.worker import Command
        with TemporaryDirectory() as tmp:
            scan_file = Path(tmp) / 'scan.json'
            with override_settings(SCAN_FILE=scan_file), \
                    mock.patch.object(local, 'read', return_value=True) as read, \
                    mock.patch.object(notify, 'notify', return_value=None) as sent:
                worker = Command()
                worker.local_scan()             # no file yet: read once, so the page says why
                worker.local_scan()
                self.assertEqual(read.call_count, 1)
                scan_file.write_text('{}')
                worker.local_scan()             # it landed: read at the next tick
                worker.local_scan()             # unchanged: not again
                self.assertEqual(read.call_count, 2)
                os.utime(scan_file, (1_000_000, 1_000_000))
                worker.local_scan()             # rewritten (the cron, 15 minutes later)
                self.assertEqual((read.call_count, sent.call_count), (3, 3))
