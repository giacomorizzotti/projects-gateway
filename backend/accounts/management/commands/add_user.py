"""Allow an auth-server account into the gateway: manage.py add_user <username>

The username must match the auth server's. The local user has no usable password:
login always goes through the auth server.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Allow an auth-server account (by username) into the gateway.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--name', default='', help='Full name, shown in the app.')

    def handle(self, username, name, **options):
        first, _, last = name.partition(' ')
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_unusable_password()
        if name:
            user.first_name, user.last_name = first, last
        user.is_active = True
        user.save()
        self.stdout.write(self.style.SUCCESS(f'{"Added" if created else "Updated"} user {username}.'))
