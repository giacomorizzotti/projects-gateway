"""Sync the GitHub profile and repos (what "Sync now" does), for the worker or by hand."""
from django.core.management.base import BaseCommand, CommandError

from catalog import github


class Command(BaseCommand):
    help = 'Read the GitHub profile and repos of GITHUB_OWNER into the catalog.'

    def handle(self, *args, **options):
        try:
            result = github.sync()
        except github.GitHubError as e:
            raise CommandError(str(e))
        if options['verbosity'] > 0:
            self.stdout.write(f"{result['repos']} repos synced, {result['created']} new, "
                              f"{result['missing']} missing on GitHub.")
