from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Platform
from monitoring import attention
from . import planning
from .models import BackupAgent, BackupJob, BackupRun, BackupTarget, JobTarget

ROME = ZoneInfo('Europe/Rome')


def at(*args):
    return datetime(*args, tzinfo=ROME)


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(name='Home server', slug='home-server', kind='home_server')
        cls.other = Platform.objects.create(name='VPS', slug='vps', kind='vps')
        cls.local = BackupTarget.objects.create(platform=cls.platform, name='disk', path='/home/backups')
        cls.share = BackupTarget.objects.create(platform=cls.platform, name='share', path='/media/share/backup',
                                                mount='/media/share')
        cls.job = BackupJob.objects.create(slug='db', name='DB', platform=cls.platform, kind='mysql', source='app',
                                           credentials='app.cnf', folder='app/db', prefix='app',
                                           frequency='daily', hour=0)
        BackupJob.objects.filter(pk=cls.job.pk).update(created_at=at(2026, 11, 1, 12))
        cls.job.refresh_from_db()
        JobTarget.objects.create(job=cls.job, target=cls.local, position=0)
        JobTarget.objects.create(job=cls.job, target=cls.share, position=1)

    def run_at(self, when, status='ok', **kw):
        return BackupRun.objects.create(job=self.job, started_at=when, finished_at=when + timedelta(minutes=1),
                                        status=status, **kw)


class ScheduleTests(Fixture):
    def test_slots(self):
        job = BackupJob(frequency='weekly', hour=0)
        self.assertEqual(planning.last_slot(job, at(2026, 11, 13, 10)), at(2026, 11, 8, 0))     # the Sunday before
        self.assertEqual(planning.next_slot(job, at(2026, 11, 13, 10)), at(2026, 11, 15, 0))
        job.frequency = 'monthly'
        self.assertEqual(planning.last_slot(job, at(2026, 11, 13, 10)), at(2026, 11, 1, 0))
        self.assertEqual(planning.next_slot(job, at(2026, 12, 13, 10)), at(2027, 1, 1, 0))
        job.frequency, job.hour = 'daily', 3
        self.assertEqual(planning.last_slot(job, at(2026, 11, 13, 2)), at(2026, 11, 12, 3))
        job.frequency = 'yearly'
        self.assertEqual(planning.last_slot(job, at(2026, 11, 13, 2)), at(2026, 1, 1, 3))

    def test_due_after_each_scheduled_time_once(self):
        self.assertEqual(planning.is_due(self.job, at(2026, 11, 13, 0, 10)), (True, False))
        self.run_at(at(2026, 11, 13, 0, 10))
        self.assertEqual(planning.is_due(self.job, at(2026, 11, 13, 0, 25)), (False, False))
        self.assertEqual(planning.is_due(self.job, at(2026, 11, 14, 0, 5)), (True, False))

    def test_a_new_job_waits_for_its_first_scheduled_time(self):
        BackupJob.objects.filter(pk=self.job.pk).update(created_at=at(2026, 11, 13, 9))
        self.job.refresh_from_db()
        self.assertEqual(planning.is_due(self.job, at(2026, 11, 13, 10)), (False, False))
        self.assertEqual(planning.is_due(self.job, at(2026, 11, 14, 0, 5)), (True, False))

    def test_back_up_now_even_when_not_scheduled(self):
        self.run_at(at(2026, 11, 13, 0, 10))
        self.job.enabled, self.job.requested_at = False, at(2026, 11, 13, 9)
        self.assertEqual(planning.is_due(self.job, at(2026, 11, 13, 9, 5)), (True, True))
        self.run_at(at(2026, 11, 13, 9, 10))
        self.assertEqual(planning.is_due(self.job, at(2026, 11, 13, 9, 15)), (False, False))

    def test_problems(self):
        self.assertEqual(planning.job_problem(self.job, at(2026, 11, 13, 4))[0], 'danger')           # missed
        self.assertIsNone(planning.job_problem(self.job, at(2026, 11, 13, 2)))                       # within grace
        self.run_at(at(2026, 11, 13, 0, 10), status='failed', error='mysqldump failed')
        self.assertIn('mysqldump failed', planning.job_problem(self.job, at(2026, 11, 13, 4))[1])
        self.run_at(at(2026, 11, 13, 0, 20), status='partial',
                    files=[{'target': 1, 'path': '/x', 'ok': False, 'error': 'not mounted'}])
        self.assertEqual(planning.job_problem(self.job, at(2026, 11, 13, 4)), (
            'warning', 'Made, but not copied everywhere (13 Nov 00:20): not mounted'))
        self.job.enabled = False
        BackupRun.objects.all().delete()
        self.assertIsNone(planning.job_problem(self.job, at(2026, 11, 20)))        # not scheduled: never missed


class AgentApiTests(Fixture):
    def setUp(self):
        self.token = BackupAgent.issue(self.platform)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f'Agent {self.token}')

    def test_a_token_is_needed_and_only_its_hash_is_kept(self):
        self.assertEqual(APIClient().post('/api/agent/checkin/', {}, format='json').status_code, 401)
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION='Agent nope')
        self.assertEqual(bad.post('/api/agent/checkin/', {}, format='json').status_code, 401)
        self.assertNotIn(self.token, str(BackupAgent.objects.values_list()))

    def test_checkin_gives_this_platforms_plan_only(self):
        BackupJob.objects.create(slug='vps-db', name='x', platform=self.other, kind='mysql', source='x',
                                 credentials='x.cnf', folder='x', prefix='x')
        plan = self.api.post('/api/agent/checkin/', {'version': '1.0', 'hostname': 'home-server'}, format='json').json()
        self.assertEqual([j['slug'] for j in plan['jobs']], ['db'])
        self.assertEqual(plan['jobs'][0]['targets'], [self.local.id, self.share.id])
        self.assertEqual({t['path'] for t in plan['targets']}, {'/home/backups', '/media/share/backup'})
        self.assertIsNotNone(BackupAgent.objects.get().last_seen_at)

    def test_runs_and_reports(self):
        report = {'job': self.job.id, 'started_at': '2026-11-13T00:00:05+01:00', 'finished_at': '2026-11-13T00:00:07+01:00',
                  'status': 'ok', 'size': 1234, 'sha256': 'a' * 64,
                  'files': [{'target': self.local.id, 'path': '/home/backups/app/db/x.sql.gz', 'ok': True}]}
        self.assertEqual(self.api.post('/api/agent/runs/', report, format='json').status_code, 201)
        other_job = BackupJob.objects.create(slug='vps-db', name='x', platform=self.other, kind='mysql', source='x',
                                             credentials='x.cnf', folder='x', prefix='x')
        self.assertEqual(self.api.post('/api/agent/runs/', {**report, 'job': other_job.id}, format='json').status_code, 404)
        self.assertEqual(self.api.post('/api/agent/report/', {'disk': {str(self.local.id): {'free': 1, 'total': 100}}},
                                       format='json').status_code, 204)
        # A user's login doesn't open the agent API, and an agent token doesn't open the user API.
        user = APIClient()
        user.force_authenticate(User.objects.create(username='me'))
        self.assertEqual(user.post('/api/agent/checkin/', {}, format='json').status_code, 403)
        self.assertEqual(self.api.get('/api/backups/').status_code, 401)


class UserApiTests(Fixture):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(User.objects.create(username='me'))

    def create(self, **kw):
        body = {'name': 'Code', 'platform': self.platform.id, 'kind': 'files', 'source': '/home/projects/x',
                'target_ids': [self.local.id], **kw}
        return self.api.post('/api/backup-jobs/', body, format='json')

    def test_create_with_defaults_and_back_up_now(self):
        r = self.create()
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertEqual((data['slug'], data['folder'], data['prefix']), ('code', 'code', 'code'))
        self.assertIn('*/node_modules/*', data['excludes'])
        self.assertEqual(self.api.post(f'/api/backup-jobs/{data["id"]}/run/').status_code, 202)
        self.assertIsNotNone(BackupJob.objects.get(pk=data['id']).requested_at)
        overview = self.api.get('/api/backups/').json()
        self.assertTrue(next(j for j in overview['jobs'] if j['id'] == data['id'])['waiting'])

    def test_nothing_that_could_become_an_option_or_escape_a_folder(self):
        errors = self.create(kind='mysql', source='--all-databases', credentials='../x.cnf').json()
        self.assertEqual(set(errors), {'source', 'credentials'})
        self.assertIn('folder', self.create(folder='../etc').json())
        self.assertIn('source', self.create(source='/home/projects/../etc').json())
        self.assertIn('excludes', self.create(excludes=['-T']).json())
        self.assertIn('target_ids', self.create(target_ids=[]).json())
        far = BackupTarget.objects.create(platform=self.other, name='vps', path='/backup')
        self.assertIn('target_ids', self.create(target_ids=[far.id]).json())


class AttentionTests(Fixture):
    def test_agent_and_space_problems(self):
        keys = lambda: {i['key']: i['severity'] for i in attention.items(at(2026, 11, 13, 4))}
        self.assertEqual(keys()['agent:home-server'], 'warning')                    # never checked in
        BackupAgent.issue(self.platform)
        BackupAgent.objects.update(last_seen_at=at(2026, 11, 13, 1),
                                   disk={str(self.local.id): {'free': 1024 ** 3, 'total': 100 * 1024 ** 3},
                                         str(self.share.id): {'error': '/media/share is not mounted'}})
        found = keys()
        self.assertEqual(found['agent:home-server'], 'danger')                      # silent for 3 hours
        self.assertEqual(found[f'target:{self.local.id}'], 'warning')              # 1 GB free
        self.assertEqual(found[f'target:{self.share.id}'], 'warning')
        self.assertEqual(found[f'backup-job:{self.job.id}'], 'danger')            # missed
