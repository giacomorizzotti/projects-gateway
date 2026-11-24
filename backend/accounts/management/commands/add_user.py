"""Allow a provider account into the gateway: manage.py add_user <username>

The username is the provider's (the OIDC_USERNAME_CLAIM claim). At the first login the local
user is bound to that provider account (accounts.Identity); --rebind forgets the binding, so the
next login with the username binds again, e.g. after the account was replaced on the provider.
The local user has no usable password: login always goes through the provider.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Allow a provider account (by username) into the gateway.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--name', default='', help='Full name, shown in the app.')
        parser.add_argument('--rebind', action='store_true',
                            help='Forget which provider account this user signs in as: the next '
                                 'login with the username binds again.')

    def handle(self, username, name, rebind, **options):
        first, _, last = name.partition(' ')
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_unusable_password()
        if name:
            user.first_name, user.last_name = first, last
        user.is_active = True
        user.save()
        self.stdout.write(self.style.SUCCESS(f'{"Added" if created else "Updated"} user {username}.'))
        if rebind:
            forgotten, _ = user.identities.all().delete()
            self.stdout.write(f'Forgot {forgotten} binding(s): the next login as {username} binds again.')
