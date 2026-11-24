"""Issue a platform's backup-agent token (replacing any old one).

The token is printed once, on stdout alone, so it can go straight into the agent's token
file without being shown:

    docker compose exec -T app python manage.py agent_token home-server \\
        | (umask 077; cat > /home/backups/.agent_token)

Only its hash is stored.
"""
from django.core.management.base import BaseCommand, CommandError

from backups.models import BackupAgent
from catalog.models import Platform


class Command(BaseCommand):
    help = "Issue a platform's backup-agent token (printed once, on stdout)."

    def add_arguments(self, parser):
        parser.add_argument('platform', help='The platform slug, e.g. home-server.')

    def handle(self, *args, platform, **options):
        found = Platform.objects.filter(slug=platform).first()
        if found is None:
            raise CommandError(f'No platform "{platform}".')
        self.stdout.write(BackupAgent.issue(found))
