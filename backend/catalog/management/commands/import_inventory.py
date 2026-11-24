"""Load an inventory (a YAML file in seed/demo.yaml's format) into the catalog.

    manage.py import_inventory [path]        # default: seed/demo.yaml, the invented demo

Meant to run ONCE, on an empty catalog: after that the gateway's database is the source of
truth. With --force it updates an existing catalog instead. Seeded objects get their fields
updated, and seeded projects/platforms get their environments, links and dependencies
REPLACED, so edits made in the gateway to those would be lost.
"""
from pathlib import Path

import yaml
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from catalog.models import (Client, Dependency, Environment, Link, Platform, Project, Repository,
                            Service, Technology)

PLATFORM_FIELDS = ['name', 'kind', 'provider', 'location', 'public_ips', 'dynamic_dns', 'hostnames',
                   'os', 'notes', 'cleanup_notes']
REPOSITORY_FIELDS = ['name', 'hosting', 'remote_url', 'local_path', 'private', 'notes']
PROJECT_FIELDS = ['name', 'group', 'status', 'description', 'notes']
ENVIRONMENT_FIELDS = ['name', 'kind', 'urls', 'runtime', 'path', 'deploy', 'notes']


class Command(BaseCommand):
    help = 'Load an inventory (YAML, seed/demo.yaml by default) into an empty catalog.'

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=str(settings.REPO_DIR / 'seed' / 'demo.yaml'))
        parser.add_argument('--force', action='store_true',
                            help='Update a catalog that already has projects (see the module docstring).')

    def handle(self, path, force, **options):
        if Project.objects.exists() and not force:
            raise CommandError('The catalog already has projects. Use --force to update it from the '
                               'seed (seeded environments, links and dependencies get replaced).')
        data = yaml.safe_load(Path(path).read_text())
        try:
            with transaction.atomic():
                counts = self.load(data)
        except ValidationError as e:
            raise CommandError(f'Invalid data: {e}')
        if options['verbosity'] > 0:
            self.stdout.write(self.style.SUCCESS(
                'Imported: ' + ', '.join(f'{n} {what}' for what, n in counts.items())))

    # -- helpers ------------------------------------------------------------------------------

    def save(self, model, lookup, values):
        obj = model.objects.filter(**lookup).first() or model(**lookup)
        for field, value in values.items():
            setattr(obj, field, value)
        try:
            obj.full_clean()
        except ValidationError as e:
            raise ValidationError(f'{model.__name__} {lookup}: {e.message_dict}')
        obj.save()
        return obj

    @staticmethod
    def pick(item, fields):
        return {f: item[f] for f in fields if f in item and item[f] is not None}

    @staticmethod
    def get(mapping, key, what, where):
        if key not in mapping:
            raise CommandError(f'{where}: unknown {what} "{key}"')
        return mapping[key]

    # -- import -------------------------------------------------------------------------------

    def load(self, data):
        techs = {}
        for t in data.get('technologies', []):
            techs[t['name']] = self.save(Technology, {'name': t['name']},
                                         {'category': t.get('category', 'other')})

        clients = {}
        for name in data.get('clients', []):
            clients[name] = self.save(Client, {'name': name}, {'slug': slugify(name)})

        platforms = {}
        for p in data.get('platforms', []):
            platform = self.save(Platform, {'slug': p['slug']}, self.pick(p, PLATFORM_FIELDS))
            platform.links.all().delete()
            for i, link in enumerate(p.get('links', [])):
                self.save(Link, {'platform': platform, 'label': link['label']},
                          {'url': link['url'], 'position': i})
            platforms[p['slug']] = platform

        repos = {}
        for r in data.get('repositories', []):
            repos[r['slug']] = self.save(Repository, {'slug': r['slug']}, self.pick(r, REPOSITORY_FIELDS))

        projects = {}
        for p in data.get('projects', []):
            where = f'project {p["slug"]}'
            values = self.pick(p, PROJECT_FIELDS)
            values['client'] = self.get(clients, p['client'], 'client', where) if p.get('client') else None
            project = self.save(Project, {'slug': p['slug']}, values)
            project.technologies.set([self.get(techs, t, 'technology', where) for t in p.get('technologies', [])])
            for slug in p.get('repositories', []):
                self.get(repos, slug, 'repository', where).projects.add(project)

            project.environments.all().delete()
            for i, env in enumerate(p.get('environments', [])):
                for url in env.get('urls', []):
                    if not url.startswith(('https://', 'http://')):
                        raise CommandError(f'{where}: "{url}" is not an http(s) URL')
                values = self.pick(env, ENVIRONMENT_FIELDS)
                values['platform'] = (self.get(platforms, env['platform'], 'platform', where)
                                      if env.get('platform') else None)
                values['checks_enabled'] = env.get('checks', True)
                values['position'] = i
                self.save(Environment, {'project': project, 'name': env['name']}, values)
            projects[p['slug']] = project

        # Dependencies last: they point at projects that may come later in the file.
        Dependency.objects.filter(project__in=projects.values()).delete()
        dependency_count = 0
        for p in data.get('projects', []):
            for dep in p.get('depends_on', []):
                where = f'project {p["slug"]} depends_on'
                source, target = projects[p['slug']], self.get(projects, dep['project'], 'project', where)
                environment = None
                if dep.get('environment'):
                    environment = source.environments.filter(name=dep['environment']).first()
                    if environment is None:
                        raise CommandError(f'{where}: unknown environment "{dep["environment"]}"')
                self.save(Dependency, {'project': source, 'depends_on': target, 'environment': environment},
                          {'kind': dep.get('kind', 'other'), 'via': dep.get('via', ''),
                           'version': str(dep.get('version', '')), 'reference': dep.get('reference', ''),
                           'notes': dep.get('notes', '')})
                dependency_count += 1

        services = {}
        for sv in data.get('services', []):
            service = self.save(Service, {'slug': sv['slug']}, self.pick(sv, ['name', 'kind', 'url', 'account', 'notes']))
            service.projects.set([self.get(projects, slug, 'project', f'service {sv["slug"]}')
                                  for slug in sv.get('projects', [])])
            services[sv['slug']] = service

        return {
            'platforms': len(platforms), 'clients': len(clients), 'technologies': len(techs),
            'repositories': len(repos), 'projects': len(projects),
            'environments': Environment.objects.filter(project__in=projects.values()).count(),
            'dependencies': dependency_count, 'services': len(services),
        }
