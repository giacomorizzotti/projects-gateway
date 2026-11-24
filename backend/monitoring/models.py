"""Live status: what the worker found when it last looked.

`UrlCheck` is the latest check of each URL (one row per environment + URL) and `CheckEvent`
records each time one went down or came back, so the history stays small: a few rows a
month instead of one per check. `MonitorState` is one row about the worker's own runs.
"""
from django.db import models

from catalog.models import Environment


class UrlCheck(models.Model):
    class State(models.TextChoices):
        UP = 'up', 'Up'
        DOWN = 'down', 'Down'

    environment = models.ForeignKey(Environment, on_delete=models.CASCADE, related_name='url_checks')
    url = models.CharField(max_length=500)
    state = models.CharField(max_length=10, choices=State.choices)    # confirmed: see failing_since
    since = models.DateTimeField()                  # when the current state began
    # A failure not confirmed yet: `state` stays as it was until the URL still fails a check
    # CONFIRM_AFTER later (checks.py). None when the latest check answered, or once down.
    failing_since = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField()
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_ms = models.PositiveIntegerField(null=True, blank=True)
    final_url = models.CharField(max_length=500, blank=True)    # after redirects
    error = models.CharField(max_length=500, blank=True)
    attempts = models.PositiveSmallIntegerField(default=1)
    ips = models.JSONField(default=list, blank=True)
    # Does the name resolve to one of its platform's addresses? None: nothing to compare.
    dns_match = models.BooleanField(null=True, blank=True)
    tls_expires_at = models.DateTimeField(null=True, blank=True)
    tls_error = models.CharField(max_length=300, blank=True)
    tls_names = models.JSONField(default=list, blank=True)       # the names the certificate covers
    # Its other names that point away from the platform: where certbot renews certificates
    # on the server itself, a renewal there can't prove them, so it fails.
    tls_elsewhere = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['environment__project__name', 'environment__position', 'url']
        constraints = [models.UniqueConstraint(fields=['environment', 'url'], name='unique_url_check')]

    def __str__(self):
        return f'{self.url} ({self.state})'


class CheckEvent(models.Model):
    """A URL went down (`state` = down, with the error) or came back up."""

    environment = models.ForeignKey(Environment, on_delete=models.CASCADE, related_name='check_events')
    url = models.CharField(max_length=500)
    at = models.DateTimeField()
    state = models.CharField(max_length=10, choices=UrlCheck.State.choices)
    detail = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-at', '-id']
        indexes = [models.Index(fields=['at'])]

    def __str__(self):
        return f'{self.url} {self.state} at {self.at:%Y-%m-%d %H:%M}'


class LocalScan(models.Model):
    """A single row: the latest snapshot of the host's git repos, nginx sites and systemd
    services, as deploy/scan_local.py wrote it (see monitoring/local.py)."""

    scanned_at = models.DateTimeField(null=True, blank=True)    # when the host script ran
    read_at = models.DateTimeField(null=True, blank=True)       # when the worker last read it
    error = models.CharField(max_length=300, blank=True)
    data = models.JSONField(default=dict, blank=True)

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]


class MonitorState(models.Model):
    """A single row: when the worker last ran the checks, and what it last notified."""

    checks_ran_at = models.DateTimeField(null=True, blank=True)
    checks_seconds = models.FloatField(null=True, blank=True)
    checks_count = models.PositiveIntegerField(default=0)
    # The last run reached nothing at all: the gateway was offline, so it was thrown away.
    checks_offline = models.BooleanField(default=False)
    # "Check now" on the Status page: the worker runs the checks at its next tick (seconds).
    check_requested_at = models.DateTimeField(null=True, blank=True)
    # Notifications: the red "needs attention" items already announced ({key: title}), so
    # each one is sent once when it appears and once when it clears.
    notified = models.JSONField(default=dict, blank=True)
    notify_sent_at = models.DateTimeField(null=True, blank=True)
    notify_error = models.CharField(max_length=300, blank=True)

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]
