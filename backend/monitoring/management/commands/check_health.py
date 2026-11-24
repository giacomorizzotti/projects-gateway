"""Run what the worker runs every few minutes, now: the health checks and the local scan's
snapshot. Then print what needs attention.

Notifications only with --notify: the dev copy and production share .env, and a run against
the dev copy shouldn't send messages.
"""
from django.core.management.base import BaseCommand

from monitoring import attention, checks, local, notify


class Command(BaseCommand):
    help = 'Check every public URL and read the local scan now, then list what needs attention.'

    def add_arguments(self, parser):
        parser.add_argument('--notify', action='store_true', help='Also send the notifications that are due.')

    def handle(self, *args, **options):
        result = checks.run()
        if result['offline']:
            self.stdout.write(self.style.WARNING(f'Nothing answered ({result["checked"]} URLs): offline?'))
        else:
            self.stdout.write(f'{result["checked"]} URLs checked, {result["down"]} down, '
                              f'{result["failing"]} failing (the worker confirms those 5 minutes later).')
        self.stdout.write('Local scan: ' + ('read' if local.read() else 'not readable'))
        if options.get('notify'):
            sent = notify.notify()
            self.stdout.write(f'Notifications: {sent["subject"]} {sent["results"]}' if sent else 'Notifications: nothing new')
        for item in attention.items():
            line = f'[{item["severity"]}] {item["title"]}' + (f': {item["detail"]}' if item['detail'] else '')
            self.stdout.write(line)
