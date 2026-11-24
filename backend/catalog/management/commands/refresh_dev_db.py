"""Replace the dev copy of the database with a fresh snapshot of the live one, then migrate it.

    ../venv/bin/python manage.py refresh_dev_db

The live database (data/gateway.sqlite3) is only read, through SQLite's backup API: safe while
the live app and worker are running, and in WAL mode a plain `cp` could copy half a write.
The snapshot is written into the dev database (DATA_DIR in .env, data/dev) the same way, so
the dev server can stay up. Then the dev copy is migrated, to match the code in the working
tree: migrations the live database doesn't have yet are applied to the copy only.

Everything only in the dev copy is lost. The command refuses to run when the settings point
at the live file itself.
"""
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


def dev_database():
    return Path(settings.DATABASES['default']['NAME'])


def copy_database(source, target):
    """Copy the SQLite database at `source` into `target`, reading `source` only."""
    src = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


class Command(BaseCommand):
    help = 'Replace the dev copy of the database with a snapshot of the live one, then migrate it.'

    def add_arguments(self, parser):
        parser.add_argument('--source', type=Path, default=settings.REPO_DIR / 'data' / 'gateway.sqlite3',
                            help='The live database (default: data/gateway.sqlite3).')

    def handle(self, *args, source, **options):
        target = dev_database()
        if not source.is_file():
            raise CommandError(f'No live database at {source}.')
        if source.resolve() == target.resolve():
            raise CommandError(f'The settings point at the live database itself ({target}): '
                               'set DATA_DIR in .env to the dev folder (data/dev) first.')
        connections['default'].close()      # nothing of ours holds the target open meanwhile
        copy_database(source, target)
        self.stdout.write(f'Copied {source} → {target}.')
        call_command('migrate', interactive=False, verbosity=1 if options['verbosity'] else 0)
