"""The backup planner: what is backed up, when, where to, and whether it happened.

An agent on each platform (deploy/backup_agent.py, from its crontab) asks the gateway which
jobs are due, makes each backup once in the job's first target, copies it to the others,
and reports back. It only runs the fixed job kinds below, and only on paths under roots
allowed in its own config on that server: nothing the gateway sends can make it do more.

No secrets here: a MySQL job names an option file (chmod 600) in the agent's credentials
folder; the agent's token is stored hashed.
"""
import hashlib
import secrets

from django.db import models

from catalog.models import Environment, Platform, Project


class BackupTarget(models.Model):
    """A folder backups are written to: a local disk, a mounted share like a NAS…"""

    class Location(models.TextChoices):
        SAME_MACHINE = 'same_machine', 'Same machine'
        HOME = 'home', 'Home (another device)'
        OFFSITE = 'offsite', 'Off-site'

    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name='backup_targets')
    name = models.CharField(max_length=100)
    path = models.CharField(max_length=500)
    # A share that must be mounted before writing (otherwise the files would land on the
    # local disk under the mount point).
    mount = models.CharField(max_length=500, blank=True)
    location = models.CharField(max_length=20, choices=Location.choices, default=Location.SAME_MACHINE)
    # Backups of each job kept here: the newest N. 0 keeps everything (deleted by hand).
    keep = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['platform__name', 'name']

    def __str__(self):
        return f'{self.platform}  ·  {self.name}'


class BackupJob(models.Model):
    class Kind(models.TextChoices):
        MYSQL = 'mysql', 'MySQL dump'
        FILES = 'files', 'Folder (zip)'
        SQLITE = 'sqlite', 'SQLite database'

    class Frequency(models.TextChoices):
        DAILY = 'daily', 'Every day'
        WEEKLY = 'weekly', 'Every week (Sunday)'
        MONTHLY = 'monthly', 'Every month (the 1st)'
        YEARLY = 'yearly', 'Every year (1 January)'

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name='backup_jobs')
    environment = models.ForeignKey(Environment, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='backup_jobs')
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name='backup_jobs')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # files / sqlite: an absolute path. mysql: the database name.
    source = models.CharField(max_length=500)
    # mysql: the option file's name in the agent's credentials folder (e.g. shop.cnf).
    credentials = models.CharField(max_length=100, blank=True)
    # files: zip -x patterns (default: node_modules and virtualenvs).
    excludes = models.JSONField(default=list, blank=True)
    # Where in each target, and how files are named: <folder>/<prefix>_DB_BK_<stamp>.sql.gz,
    # <prefix>_BK_<stamp>.zip, <prefix>_DB_BK_<stamp>.sqlite3.gz (the names the old scripts used).
    folder = models.CharField(max_length=200)
    prefix = models.CharField(max_length=100)
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.DAILY)
    hour = models.PositiveSmallIntegerField(default=0)          # local time
    # Made in the first (by position), then copied to the others.
    targets = models.ManyToManyField(BackupTarget, through='JobTarget', related_name='jobs')
    enabled = models.BooleanField(default=True)
    # "Back up now": the agent runs it at its next check-in.
    requested_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # A new job waits for its first scheduled time (not the agent's next check-in).
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['platform__name', 'name']

    def __str__(self):
        return self.name

    def ordered_targets(self):
        return [jt.target for jt in self.job_targets.select_related('target').order_by('position', 'id')]


class JobTarget(models.Model):
    job = models.ForeignKey(BackupJob, on_delete=models.CASCADE, related_name='job_targets')
    target = models.ForeignKey(BackupTarget, on_delete=models.CASCADE, related_name='job_targets')
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['job', 'target'], name='unique_job_target')]


class BackupRun(models.Model):
    class Status(models.TextChoices):
        OK = 'ok', 'OK'
        PARTIAL = 'partial', 'Made, but not copied everywhere'
        FAILED = 'failed', 'Failed'

    job = models.ForeignKey(BackupJob, on_delete=models.CASCADE, related_name='runs')
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices)
    size = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    # [{"target": id, "path": "…", "ok": true, "error": ""}, …]
    files = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    requested = models.BooleanField(default=False)               # "Back up now", not the schedule

    class Meta:
        ordering = ['-started_at', '-id']
        indexes = [models.Index(fields=['job', '-started_at'])]

    def __str__(self):
        return f'{self.job} {self.started_at:%Y-%m-%d %H:%M} {self.status}'


class BackupAgent(models.Model):
    """The agent on one platform: its token (hashed) and what it last reported."""

    platform = models.OneToOneField(Platform, on_delete=models.CASCADE, related_name='backup_agent')
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    version = models.CharField(max_length=20, blank=True)
    hostname = models.CharField(max_length=100, blank=True)
    # {target id: {"free": bytes, "total": bytes, "error": ""}}
    disk = models.JSONField(default=dict, blank=True)
    # {job id: {target id: {"count": n, "bytes": n}}}
    usage = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f'Agent on {self.platform}'

    @staticmethod
    def hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def issue(cls, platform):
        """A new token for the platform's agent (replacing any old one). Returned once, never stored."""
        token = secrets.token_urlsafe(32)
        cls.objects.update_or_create(platform=platform, defaults={'token_hash': cls.hash(token)})
        return token
