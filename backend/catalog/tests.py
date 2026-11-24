import tempfile
from unittest import mock
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Dependency, Environment, Platform, Project, ProjectGroup, Repository, Service, Technology,
                     TechnologyCategory)


class SeedTests(TestCase):
    def test_demo_seed_imports_cleanly(self):
        call_command('import_inventory', verbosity=0)          # seed/demo.yaml
        self.assertEqual(Project.objects.count(), 7)
        shop = Project.objects.get(slug='rental-shop')
        self.assertTrue(Dependency.objects.filter(project=shop, depends_on__slug='shop-api').exists())
        # Hosts the gateway can't reach get no health checks.
        self.assertFalse(Environment.objects.get(project__slug='demo-ui', name='Local').checks_enabled)
        self.assertEqual(Platform.objects.get(slug='home-server').dynamic_dns, 'home.example')

    def test_seed_records_how_a_dependency_is_included(self):
        call_command('import_inventory', verbosity=0)
        shop = {d.environment.name: d for d in Dependency.objects.filter(project__slug='rental-shop', depends_on__slug='demo-ui')}
        self.assertEqual((shop['TEST'].via, shop['PROD'].via), ('symlink', 'git'))
        self.assertEqual((shop['TEST'].reference, shop['PROD'].version), ('frontend/src/ui', 'v1.4.0'))
        site = Dependency.objects.get(project__slug='northwind-site', depends_on__slug='demo-ui')
        self.assertEqual((site.via, site.version, site.environment), ('cdn', '1.4.0', None))

    def test_refuses_to_overwrite_without_force(self):
        call_command('import_inventory', verbosity=0)
        with self.assertRaisesMessage(CommandError, 'already has projects'):
            call_command('import_inventory', verbosity=0)

    def test_force_is_idempotent(self):
        call_command('import_inventory', verbosity=0)
        counts = (Project.objects.count(), Environment.objects.count(), Dependency.objects.count())
        call_command('import_inventory', force=True, verbosity=0)
        self.assertEqual(counts, (Project.objects.count(), Environment.objects.count(),
                                  Dependency.objects.count()))

    def _import_text(self, text):
        with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False) as f:
            f.write(text)
        try:
            call_command('import_inventory', f.name, verbosity=0)
        finally:
            Path(f.name).unlink()

    def test_unknown_platform_rolls_everything_back(self):
        text = ('projects:\n'
                '  - {slug: a, name: A, group: tools}\n'
                '  - slug: b\n    name: B\n    group: tools\n'
                '    environments: [{name: PROD, platform: nowhere}]\n')
        with self.assertRaisesMessage(CommandError, 'unknown platform "nowhere"'):
            self._import_text(text)
        self.assertFalse(Project.objects.exists())

    def test_invalid_group_is_rejected(self):
        with self.assertRaisesMessage(CommandError, 'Invalid data'):
            self._import_text('projects:\n  - {slug: a, name: A, group: not-a-group}\n')

    def test_non_http_url_is_rejected(self):
        text = ('projects:\n  - slug: a\n    name: A\n    group: tools\n'
                '    environments: [{name: PROD, urls: ["ftp://x"]}]\n')
        with self.assertRaisesMessage(CommandError, 'not an http(s) URL'):
            self._import_text(text)


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('import_inventory', verbosity=0)
        cls.user = User.objects.create(username='alice')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_everything_needs_login(self):
        anon = APIClient()
        for url in ['/api/projects/', '/api/platforms/', '/api/repositories/', '/api/choices/',
                    '/api/projects/rental-shop/']:
            self.assertEqual(anon.get(url).status_code, 401, url)

    def test_project_list_has_environments_and_platforms(self):
        data = self.api.get('/api/projects/').json()
        shop = next(p for p in data if p['slug'] == 'rental-shop')
        prod = next(e for e in shop['environments'] if e['name'] == 'PROD')
        self.assertEqual(prod['platform_detail']['slug'], 'cloud-vps')
        self.assertIn('https://shop.acme.example/', prod['urls'])
        self.assertIn('Django', shop['technology_names'])

    def test_project_detail_has_dependencies_both_ways(self):
        api = self.api.get('/api/projects/shop-api/').json()
        self.assertIn('rental-shop', [d['project_detail']['slug'] for d in api['dependents']])
        shop = self.api.get('/api/projects/rental-shop/').json()
        self.assertIn('shop-api', [d['depends_on_detail']['slug'] for d in shop['dependencies']])

    def test_filters(self):
        on_vps = {p['slug'] for p in self.api.get('/api/projects/?platform=cloud-vps').json()}
        self.assertIn('shop-api', on_vps)
        self.assertNotIn('northwind-site', on_vps)
        archive = {p['group'] for p in self.api.get('/api/projects/?group=archive').json()}
        self.assertEqual(archive, {'archive'})
        # A project with several environments on the same platform appears once.
        home = [p['slug'] for p in self.api.get('/api/projects/?platform=home-server').json()]
        self.assertEqual(home.count('status-board'), 1)

    def test_platform_detail_lists_what_it_hosts(self):
        data = self.api.get('/api/platforms/cloud-vps/').json()
        hosted = {e['project_detail']['slug'] for e in data['environments']}
        self.assertTrue({'rental-shop', 'shop-api', 'demo-ui'} <= hosted)

    def test_create_update_delete_project(self):
        resp = self.api.post('/api/projects/', {'slug': 'new-thing', 'name': 'New thing',
                                                'group': 'tools'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = self.api.patch('/api/projects/new-thing/', {'status': 'archived'}, format='json')
        self.assertEqual(resp.json()['status'], 'archived')
        self.assertEqual(self.api.delete('/api/projects/new-thing/').status_code, 204)

    def test_notes_are_markdown_unless_switched_to_plain(self):
        resp = self.api.post('/api/projects/', {'name': 'Noted', 'group': 'tools',
                                                'notes': '- one\n- two'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(resp.json()['notes_markdown'])                 # new projects: Markdown
        resp = self.api.patch('/api/projects/noted/', {'notes_markdown': False}, format='json')
        self.assertFalse(resp.json()['notes_markdown'])
        self.assertFalse(Project.objects.get(slug='noted').notes_markdown)

    def test_environment_validation(self):
        project = Project.objects.get(slug='rental-shop')
        resp = self.api.post('/api/environments/', {'project': project.id, 'name': 'X',
                                                    'urls': 'not-a-list'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_dependency_on_itself_is_rejected(self):
        shop = Project.objects.get(slug='rental-shop')
        resp = self.api.post('/api/dependencies/', {'project': shop.id, 'depends_on': shop.id},
                             format='json')
        self.assertEqual(resp.status_code, 400)

    def test_github_fields_are_read_only(self):
        resp = self.api.patch('/api/repositories/rental-shop/', {'language': 'COBOL', 'notes': 'n'}, format='json')
        self.assertEqual(resp.status_code, 200)
        repo = Repository.objects.get(slug='rental-shop')
        self.assertEqual(repo.notes, 'n')
        self.assertEqual(repo.language, '')

    def test_choices(self):
        data = self.api.get('/api/choices/').json()
        self.assertEqual(data['project_groups'][0], {'value': 'libraries', 'label': 'Libraries', 'hidden': False})
        self.assertEqual(data['project_groups'][-1], {'value': 'archive', 'label': 'Archive', 'hidden': True})


class WriteTests(TestCase):
    """What the edit forms rely on."""

    @classmethod
    def setUpTestData(cls):
        call_command('import_inventory', verbosity=0)
        cls.user = User.objects.create(username='alice')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def post(self, url, data):
        return self.api.post(url, data, format='json')

    def test_slug_comes_from_the_name_and_is_unique(self):
        first = self.post('/api/projects/', {'name': 'Shiny New Thing!', 'group': 'tools'})
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.json()['slug'], 'shiny-new-thing')
        second = self.post('/api/projects/', {'name': 'Shiny new thing', 'group': 'tools', 'slug': ''})
        self.assertEqual(second.json()['slug'], 'shiny-new-thing-2')
        self.assertEqual(self.post('/api/clients/', {'name': 'ACME Srl'}).json()['slug'], 'acme-srl')

    def test_blank_slug_on_update_keeps_it(self):
        resp = self.api.patch('/api/projects/rental-shop/', {'slug': '', 'description': 'd'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['slug'], 'rental-shop')

    def test_project_form_links_repos_services_and_tech(self):
        repo = Repository.objects.get(slug='rental-shop')
        tech = self.post('/api/technologies/', {'name': 'Elixir'}).json()
        service = self.post('/api/services/', {'name': 'Sentry'}).json()
        resp = self.post('/api/projects/', {
            'name': 'Linked', 'group': 'software', 'technologies': [tech['id']],
            'repository_ids': [repo.id], 'service_ids': [service['id']]})
        self.assertEqual(resp.status_code, 201, resp.content)
        project = Project.objects.get(slug='linked')
        self.assertIn(project, repo.projects.all())
        self.assertEqual([s.name for s in project.services.all()], ['Sentry'])
        # Unlinking from the project side leaves the repo itself alone.
        self.api.patch('/api/projects/linked/', {'repository_ids': []}, format='json')
        self.assertNotIn(project, repo.projects.all())
        self.assertTrue(Repository.objects.filter(slug='rental-shop').exists())

    def test_settings_manage_the_groups(self):
        created = self.post('/api/groups/', {'name': 'Client sites', 'slug': 'ignored', 'position': 1})
        self.assertEqual(created.status_code, 201, created.content)
        group = created.json()
        self.assertEqual((group['slug'], group['position'], group['hidden']), ('client-sites', 9, False))
        project = self.post('/api/projects/', {'name': 'Moved', 'group': 'client-sites'})
        self.assertEqual(project.status_code, 201, project.content)
        self.assertEqual(project.json()['group_label'], 'Client sites')
        self.assertEqual(self.post('/api/projects/', {'name': 'Lost', 'group': 'nowhere'}).status_code, 400)

        # Renamed: the slug, and so the projects, stay as they are.
        renamed = self.api.patch(f'/api/groups/{group["id"]}/', {'name': 'Clients', 'slug': 'x'}, format='json')
        self.assertEqual((renamed.json()['name'], renamed.json()['slug']), ('Clients', 'client-sites'))
        self.assertEqual(self.api.get('/api/projects/moved/').json()['group_label'], 'Clients')

        # Reordered: every id, once.
        ids = list(ProjectGroup.objects.values_list('id', flat=True))
        new_order = [group['id']] + [i for i in ids if i != group['id']]
        self.assertEqual(self.post('/api/groups/reorder/', {'ids': new_order[1:]}).status_code, 400)
        self.assertEqual(self.post('/api/groups/reorder/', {'ids': new_order}).status_code, 200)
        self.assertEqual(self.api.get('/api/choices/').json()['project_groups'][0]['value'], 'client-sites')

        # Deleted only when empty.
        refused = self.api.delete(f'/api/groups/{group["id"]}/')
        self.assertEqual(refused.status_code, 400)
        self.assertIn('1 project is in Clients', refused.json()['detail'])
        self.api.patch('/api/projects/moved/', {'group': 'tools'}, format='json')
        self.assertEqual(self.api.delete(f'/api/groups/{group["id"]}/').status_code, 204)

    def test_settings_manage_the_technology_categories(self):
        self.assertEqual([c['value'] for c in self.api.get('/api/choices/').json()['technology_categories']],
                         ['cms', 'database', 'framework', 'infra', 'language', 'library', 'other'])
        created = self.post('/api/technology-categories/', {'name': 'Build tools', 'slug': 'ignored'})
        self.assertEqual(created.status_code, 201, created.content)
        category = created.json()
        self.assertEqual((category['slug'], category['technology_count']), ('build-tools', 0))
        tech = self.post('/api/technologies/', {'name': 'Vite 9', 'category': 'build-tools'})
        self.assertEqual(tech.status_code, 201, tech.content)
        self.assertEqual(self.post('/api/technologies/', {'name': 'Lost', 'category': 'nowhere'}).status_code, 400)
        # Created on the spot (name only): "other", as before; no category once "other" is gone.
        self.assertEqual(self.post('/api/technologies/', {'name': 'Spot'}).json()['category'], 'other')

        # Renamed: the slug, and so the technologies, stay as they are.
        renamed = self.api.patch(f'/api/technology-categories/{category["id"]}/', {'name': 'Build', 'slug': 'x'}, format='json')
        self.assertEqual((renamed.json()['name'], renamed.json()['slug'], renamed.json()['technology_count']),
                         ('Build', 'build-tools', 1))
        self.assertIn({'value': 'build-tools', 'label': 'Build'}, self.api.get('/api/choices/').json()['technology_categories'])

        # Deleted only when empty.
        refused = self.api.delete(f'/api/technology-categories/{category["id"]}/')
        self.assertEqual(refused.status_code, 400)
        self.assertIn('1 technology is in Build', refused.json()['detail'])
        self.api.patch(f'/api/technologies/{tech.json()["id"]}/', {'category': ''}, format='json')
        self.assertEqual(self.api.delete(f'/api/technology-categories/{category["id"]}/').status_code, 204)
        Technology.objects.filter(category='other').update(category='')
        TechnologyCategory.objects.filter(slug='other').delete()
        self.assertEqual(self.post('/api/technologies/', {'name': 'Spot 2'}).json()['category'], '')

    def test_clients_and_technologies_say_what_uses_them(self):
        client = self.post('/api/clients/', {'name': 'ACME'}).json()
        self.assertEqual((client['project_count'], client['domain_count']), (0, 0))
        self.post('/api/projects/', {'name': 'For ACME', 'group': 'tools', 'client': client['id']})
        listed = {c['name']: c for c in self.api.get('/api/clients/').json()}
        self.assertEqual(listed['ACME']['project_count'], 1)
        shop_techs = Project.objects.get(slug='rental-shop').technologies.count()
        self.assertGreater(shop_techs, 0)
        techs = self.api.get('/api/technologies/').json()
        self.assertTrue(all('project_count' in t for t in techs))
        # Deleting a client leaves its projects without one.
        self.assertEqual(self.api.delete(f'/api/clients/{client["id"]}/').status_code, 204)
        self.assertIsNone(Project.objects.get(slug='for-acme').client)

    def test_services_page_creates_edits_and_deletes_a_service(self):
        shop, site = Project.objects.get(slug='rental-shop'), Project.objects.get(slug='northwind-site')
        resp = self.post('/api/services/', {'name': 'Iubenda', 'kind': 'Privacy (GDPR)', 'url': 'https://www.iubenda.com/',
                                            'account': 'the agency account', 'projects': [shop.id]})
        self.assertEqual(resp.status_code, 201, resp.content)
        service = resp.json()
        self.assertEqual((service['slug'], service['account']), ('iubenda', 'the agency account'))
        self.assertEqual([p['slug'] for p in service['project_details']], ['rental-shop'])
        resp = self.api.patch('/api/services/iubenda/', {'projects': [shop.id, site.id]}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(sorted(p.slug for p in Service.objects.get(slug='iubenda').projects.all()), ['northwind-site', 'rental-shop'])
        self.assertEqual(self.post('/api/services/', {'name': 'Bad', 'url': 'not a url'}).status_code, 400)
        self.assertEqual(self.api.delete('/api/services/iubenda/').status_code, 204)
        self.assertTrue(Project.objects.filter(slug='rental-shop').exists())

    def test_environment_urls_and_position(self):
        project = self.post('/api/projects/', {'name': 'Envs', 'group': 'tools'}).json()
        bad = self.post('/api/environments/', {'project': project['id'], 'name': 'PROD',
                                               'urls': ['ftp://example.com']})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('urls', bad.json())
        first = self.post('/api/environments/', {'project': project['id'], 'name': 'PROD',
                                                 'urls': [' https://example.com/ ', '']}).json()
        self.assertEqual(first['urls'], ['https://example.com/'])
        second = self.post('/api/environments/', {'project': project['id'], 'name': 'DEV'}).json()
        self.assertGreater(second['position'], first['position'])

    def test_duplicate_dependency_has_a_readable_error(self):
        shop, api = Project.objects.get(slug='rental-shop'), Project.objects.get(slug='shop-api')
        resp = self.post('/api/dependencies/', {'project': shop.id, 'depends_on': api.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['non_field_errors'], ['This dependency is already recorded.'])

    def test_dependencies_per_environment(self):
        site = self.post('/api/projects/', {'name': 'WP site', 'group': 'websites'}).json()
        dev = self.post('/api/environments/', {'project': site['id'], 'name': 'DEV'}).json()
        prod = self.post('/api/environments/', {'project': site['id'], 'name': 'PROD'}).json()
        theme = Project.objects.get(slug='demo-ui')
        body = {'project': site['id'], 'depends_on': theme.id, 'kind': 'ui_library'}
        self.assertEqual(self.post('/api/dependencies/', {**body, 'environment': dev['id'], 'via': 'symlink'}).status_code, 201)
        self.assertEqual(self.post('/api/dependencies/', {**body, 'environment': prod['id'], 'via': 'git'}).status_code, 201)
        self.assertEqual(self.post('/api/dependencies/', body).status_code, 201)      # project-wide
        again = self.post('/api/dependencies/', {**body, 'environment': prod['id']})
        self.assertEqual(again.json()['non_field_errors'], ['This dependency is already recorded for PROD.'])
        self.assertEqual(self.post('/api/dependencies/', body).status_code, 400)
        shop_prod = Environment.objects.get(project__slug='rental-shop', name='PROD')
        other = self.post('/api/dependencies/', {**body, 'environment': shop_prod.id})
        self.assertIn('environment', other.json())
        self.assertEqual(self.post('/api/dependencies/', {**body, 'via': 'carrier-pigeon'}).status_code, 400)

    def test_links_need_one_owner_and_go_last(self):
        shop = Project.objects.get(slug='rental-shop')
        a = self.post('/api/links/', {'label': 'A', 'url': 'https://a.example', 'project': shop.id}).json()
        b = self.post('/api/links/', {'label': 'B', 'url': 'https://b.example', 'project': shop.id}).json()
        self.assertGreater(b['position'], a['position'])
        self.assertEqual(self.post('/api/links/', {'label': 'C', 'url': 'https://c.example'}).status_code, 400)

    def test_deleting_a_platform_keeps_its_environments(self):
        count = Environment.objects.filter(platform__slug='shared-hosting').count()
        self.assertGreater(count, 0)
        self.assertEqual(self.api.delete('/api/platforms/shared-hosting/').status_code, 204)
        self.assertEqual(Environment.objects.filter(platform__isnull=True).count() >= count, True)


class SeedDevDataTests(TestCase):
    def test_demo_catalog_keeps_the_logins_and_has_something_everywhere(self):
        from django.contrib.auth.models import User
        from django.test import override_settings
        from domains.models import Domain
        from monitoring import attention
        from monitoring.models import UrlCheck
        User.objects.create(username='me', first_name='Me')
        Project.objects.create(name='Old', slug='old-catalog', group='tools')      # what was there, to be replaced
        with override_settings(DEBUG=True):
            call_command('seed_dev_data', user=['guest'], verbosity=0)
        self.assertEqual(sorted(User.objects.values_list('username', flat=True)), ['guest', 'me'])
        self.assertEqual(User.objects.get(username='me').first_name, 'Me')
        self.assertFalse(Project.objects.filter(slug='old-catalog').exists())  # replaced, not merged
        self.assertTrue(Platform.objects.filter(slug=settings.SCAN_PLATFORM, kind='home_server').exists())
        self.assertTrue(Project.objects.filter(slug='rental-shop').exists())
        self.assertTrue(ProjectGroup.objects.filter(slug='archive', hidden=True).exists())
        self.assertTrue(UrlCheck.objects.filter(state='down').exists())
        self.assertEqual(Domain.objects.count(), 4)
        kinds = {i['kind'] for i in attention.items()}
        self.assertTrue({'down', 'backup', 'domain', 'tls', 'service', 'nginx', 'git'} <= kinds, kinds)

    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            call_command('seed_dev_data', user=['guest'], verbosity=0)     # tests run with DEBUG off


class RefreshDevDbTests(TestCase):
    def test_copies_without_writing_the_source(self):
        import sqlite3
        from catalog.management.commands.refresh_dev_db import copy_database
        with tempfile.TemporaryDirectory() as tmp:
            live, dev = Path(tmp) / 'live.sqlite3', Path(tmp) / 'dev.sqlite3'
            with sqlite3.connect(live) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE t (x)')
                db.execute("INSERT INTO t VALUES ('live')")
            with sqlite3.connect(dev) as db:
                db.execute('CREATE TABLE old (y)')
            before = live.stat().st_mtime_ns
            copy_database(live, dev)
            with sqlite3.connect(dev) as db:
                self.assertEqual(db.execute('SELECT x FROM t').fetchall(), [('live',)])
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name = 'old'").fetchone(), (0,))
            self.assertEqual(live.stat().st_mtime_ns, before)

    def test_refuses_to_copy_onto_the_live_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / 'gateway.sqlite3'
            live.write_bytes(b'')
            with mock.patch('catalog.management.commands.refresh_dev_db.dev_database', return_value=live), \
                 self.assertRaisesMessage(CommandError, 'point at the live database'):
                call_command('refresh_dev_db', source=live, verbosity=0)


class SpaFallbackTests(TestCase):
    def test_frontend_routes_get_index_or_503(self):
        resp = self.client.get('/projects/rental-shop')
        expected = 200 if (settings.FRONTEND_DIST / 'index.html').is_file() else 503
        self.assertEqual(resp.status_code, expected)

    def test_unknown_api_route_is_not_the_spa(self):
        self.assertEqual(self.client.get('/api/nope/').status_code, 404)


class FakeResponse:
    def __init__(self, data, status=200, headers=None, next_url=None):
        self._data, self.status_code = data, status
        self.ok = status < 400
        self.headers = headers or {}
        self.links = {'next': {'url': next_url}} if next_url else {}

    def json(self):
        return self._data


def gh_repo(id, name, owner='demo', **extra):
    return {'id': id, 'name': name, 'owner': {'login': owner}, 'private': True,
            'html_url': f'https://github.com/{owner}/{name}', 'ssh_url': f'git@github.com:{owner}/{name}.git',
            'description': f'{name} desc', 'default_branch': 'main', 'language': 'Python',
            'topics': [], 'archived': False, 'fork': False, 'pushed_at': '2026-11-10T10:00:00Z',
            'open_issues_count': 2, **extra}


class GitHubSyncTests(TestCase):
    USER = {'login': 'demo', 'name': 'Demo', 'bio': 'b', 'followers': 3,
            'avatar_url': 'https://avatars.githubusercontent.com/u/1', 'html_url': 'https://github.com/demo'}
    EXPIRY = {'github-authentication-token-expiration': '2027-02-08 12:00:00 +0100'}

    @classmethod
    def setUpTestData(cls):
        call_command('import_inventory', verbosity=0)
        cls.user = User.objects.create(username='alice')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def fake_github(self, repos_pages, user=None):
        def get(session, url, params=None, timeout=None):
            if url.endswith('/user'):
                return FakeResponse(user or self.USER, headers=self.EXPIRY)
            page = int(url.rsplit('page=', 1)[1]) if 'page=' in url else 1
            next_url = (f'https://api.github.com/user/repos?page={page + 1}'
                        if page < len(repos_pages) else None)
            return FakeResponse(repos_pages[page - 1], headers=self.EXPIRY, next_url=next_url)
        return mock.patch('requests.Session.get', get)

    def sync(self):
        with self.settings(GITHUB_TOKEN='test-token', GITHUB_OWNER='demo'):
            return self.api.post('/api/github/sync/')

    def test_parse_remote(self):
        from .github import parse_remote
        for url in ['git@github.com:Owner/Repo.git', 'https://github.com/owner/repo',
                    'https://github.com/owner/repo.git/', 'ssh://git@github.com/owner/repo.git']:
            self.assertEqual(parse_remote(url), ('owner', 'repo'), url)
        self.assertIsNone(parse_remote('git@bitbucket.org:o/r.git'))
        self.assertIsNone(parse_remote(''))

    def test_sync_matches_creates_and_flags(self):
        pages = [[gh_repo(1, 'rental-shop'), gh_repo(2, 'brand-new', private=False)],
                 [gh_repo(3, 'Demo-UI', archived=True), gh_repo(9, 'not-mine', owner='someone-else')]]
        with self.fake_github(pages):
            resp = self.sync()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['result'], {'repos': 3, 'created': 1, 'missing': 1})

        shop = Repository.objects.get(slug='rental-shop')         # matched by its remote URL
        self.assertEqual((shop.github_id, shop.language, shop.open_issues), (1, 'Python', 2))
        self.assertTrue(shop.projects.exists())
        self.assertEqual(Repository.objects.get(slug='demo-ui').github_id, 3)   # case-insensitive
        new = Repository.objects.get(github_id=2)
        self.assertEqual((new.slug, new.remote_url, new.private), ('brand-new', 'git@github.com:demo/brand-new.git', False))
        self.assertFalse(Repository.objects.filter(name='not-mine').exists())
        # The owner's repos GitHub didn't list are flagged; an upstream clone isn't.
        self.assertTrue(Repository.objects.get(slug='status-board').github_missing)
        self.assertFalse(Repository.objects.get(slug='uptime-widget').github_missing)

        status = self.api.get('/api/github/').json()
        self.assertEqual(status['profile']['login'], 'demo')
        self.assertTrue(status['token_expires_at'].startswith('2027-02-08T11:00'))
        self.assertEqual(status['counts']['unlinked'], 1)        # brand-new; demo-ui is archived
        self.assertNotIn('test-token', resp.content.decode())

    def test_second_sync_matches_by_id_and_clears_flags(self):
        with self.fake_github([[gh_repo(1, 'rental-shop')]]):
            self.sync()
        self.assertTrue(Repository.objects.get(slug='demo-ui').github_missing)
        with self.fake_github([[gh_repo(1, 'rental-shop-renamed'), gh_repo(3, 'demo-ui')]]):
            self.assertEqual(self.sync().json()['result']['created'], 0)
        self.assertEqual(Repository.objects.get(github_id=1).slug, 'rental-shop')
        self.assertFalse(Repository.objects.get(slug='demo-ui').github_missing)

    def test_token_of_another_account_is_refused(self):
        with self.fake_github([[]], user={**self.USER, 'login': 'intruder'}):
            resp = self.sync()
        self.assertEqual(resp.status_code, 502)
        self.assertIn('intruder', resp.json()['detail'])
        self.assertFalse(Repository.objects.filter(github_missing=True).exists())
        self.assertIn('intruder', self.api.get('/api/github/').json()['last_error'])

    def test_rejected_token_and_no_token(self):
        def get(session, url, params=None, timeout=None):
            return FakeResponse({'message': 'Bad credentials'}, status=401)
        with mock.patch('requests.Session.get', get):
            self.assertIn('rejected the token', self.sync().json()['detail'])
        with self.settings(GITHUB_TOKEN=''):
            resp = self.api.post('/api/github/sync/')
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.json()['configured'])

    def test_needs_login(self):
        self.assertEqual(APIClient().get('/api/github/').status_code, 401)
        self.assertEqual(APIClient().post('/api/github/sync/').status_code, 401)
