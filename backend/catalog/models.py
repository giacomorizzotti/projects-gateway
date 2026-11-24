"""The catalog: what projects exist, where each environment runs, which repos, which tech.

Secrets are never stored here, only pointers to where they live.
"""
from django.core.exceptions import ValidationError
from django.db import models


class PlatformKind(models.Model):
    """The platforms' kinds (Home server, VPS, Shared hosting…), managed on the Settings page. A
    platform keeps its kind's slug (`Platform.kind`), so renaming a kind never touches the
    platforms. One with platforms can't be deleted."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    # The platform renews its certificates itself (certbot over HTTP), so every name on one must
    # point there: the health checks flag one that points elsewhere (monitoring.checks). Off
    # where the provider renews them, by its own means.
    renews_certificates = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Platform(models.Model):
    """Where things run: a home server, a VPS, shared hosting, a client's server…"""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    kind = models.CharField(max_length=60)      # a PlatformKind's slug
    provider = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=100, blank=True)
    public_ips = models.JSONField(default=list, blank=True)
    # For a dynamic IP: the DNS name that always points to it (resolved when checking).
    dynamic_dns = models.CharField(max_length=255, blank=True)
    hostnames = models.JSONField(default=list, blank=True)
    os = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    cleanup_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        # The import and the admin validate through here (the API's serializer checks it too).
        if self.kind and not PlatformKind.objects.filter(slug=self.kind).exists():
            raise ValidationError({'kind': f'No such platform kind: "{self.kind}".'})


class Client(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TechnologyCategory(models.Model):
    """The technologies' categories (Language, Framework…), managed on the Settings page. A
    technology keeps its category's slug (`Technology.category`), so renaming a category never
    touches the technologies. One with technologies in it can't be deleted."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'technology categories'

    def __str__(self):
        return self.name


class Technology(models.Model):
    name = models.CharField(max_length=60, unique=True)
    # A TechnologyCategory's slug, '' for none. Left out, it's "other" while that category
    # exists (TechnologySerializer.create), as before categories could be managed.
    category = models.CharField(max_length=60, blank=True, default='')

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'technologies'

    def __str__(self):
        return self.name


class ProjectGroup(models.Model):
    """The dashboard's sections, managed on the Settings page. A project keeps its group's slug
    (`Project.group`), so renaming a group or changing the order never touches the projects.
    A hidden group (Archive) is off the dashboard unless "show archived" is on, and out of the
    health checks."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    position = models.PositiveIntegerField(default=0)
    hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        return self.name


class Project(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        DEVELOPMENT = 'development', 'In development'
        MAINTENANCE = 'maintenance', 'Maintenance'
        DISCONTINUED = 'discontinued', 'Discontinued'
        ARCHIVED = 'archived', 'Archived'

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    group = models.CharField(max_length=60)        # a ProjectGroup's slug
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='projects')
    description = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    # The notes are Markdown, or plain text (the form's Plain/Markdown switch): those written
    # before Markdown came (2026-11-20) stay plain, so a stray # or * never turns into formatting.
    notes_markdown = models.BooleanField(default=True)
    technologies = models.ManyToManyField(Technology, blank=True, related_name='projects')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        # The import and the admin validate through here (the API's serializer checks it too).
        if self.group and not ProjectGroup.objects.filter(slug=self.group).exists():
            raise ValidationError({'group': f'No such group: "{self.group}".'})


class Environment(models.Model):
    """One running copy of a project (PROD, DEV, a DEM…), on one platform."""

    class Kind(models.TextChoices):
        PROD = 'prod', 'PROD'
        TEST = 'test', 'TEST'
        DEV = 'dev', 'DEV'
        LOCAL = 'local', 'Local'
        OTHER = 'other', 'Other'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='environments')
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PROD)
    urls = models.JSONField(default=list, blank=True)
    platform = models.ForeignKey(Platform, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='environments')
    runtime = models.CharField(max_length=100, blank=True)
    path = models.CharField(max_length=255, blank=True)
    deploy = models.CharField(max_length=255, blank=True)
    # Off for internal-only hosts that the gateway can't reach.
    checks_enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['project__name', 'position', 'id']

    def __str__(self):
        return f'{self.project}&nbsp;&nbsp;·&nbsp;&nbsp;{self.name}'


class RepositoryHosting(models.Model):
    """Where repositories are hosted (GitHub, Bitbucket, Local only…), managed on the Settings
    page. A repository keeps its hosting's slug (`Repository.hosting`), so renaming one never
    touches the repositories. One with repositories can't be deleted."""

    # The GitHub sync's: it puts the repos it finds there, and makes the entry again if it's gone.
    GITHUB = 'github'
    LOCAL = 'local'

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Repository(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    # A RepositoryHosting's slug.
    hosting = models.CharField(max_length=60, default=RepositoryHosting.LOCAL)
    remote_url = models.CharField(max_length=255, blank=True)
    local_path = models.CharField(max_length=255, blank=True)
    private = models.BooleanField(default=True)
    projects = models.ManyToManyField(Project, blank=True, related_name='repositories')
    notes = models.TextField(blank=True)

    # Filled by the GitHub sync (GitHub repos only).
    github_id = models.BigIntegerField(null=True, blank=True, unique=True)
    github_url = models.URLField(blank=True)
    github_description = models.CharField(max_length=500, blank=True)
    default_branch = models.CharField(max_length=100, blank=True)
    language = models.CharField(max_length=60, blank=True)
    topics = models.JSONField(default=list, blank=True)
    archived = models.BooleanField(default=False)
    fork = models.BooleanField(default=False)
    pushed_at = models.DateTimeField(null=True, blank=True)
    open_issues = models.PositiveIntegerField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    # One of the owner's GitHub repos that the last sync didn't see: deleted, renamed away,
    # or outside the token's repository list.
    github_missing = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'repositories'

    def __str__(self):
        return self.name

    def clean(self):
        # The import and the admin validate through here (the API's serializer checks it too).
        if self.hosting and not RepositoryHosting.objects.filter(slug=self.hosting).exists():
            raise ValidationError({'hosting': f'No such repository hosting: "{self.hosting}".'})


class Dependency(models.Model):
    """`project` depends on `depends_on` (an app → its API, an app → the auth server, a site → a UI library…).

    `via`, `version` and `reference` say how it's included, which is what decides how a
    change to `depends_on` reaches it: at once (CDN @main, a symlink), at the next build,
    or only by hand (a pinned version, a copy, a git clone to pull). When one environment
    includes it differently (DEV symlinked, PROD deployed with git), each gets its own row
    with `environment` set; a row without one covers the whole project.
    """

    class Kind(models.TextChoices):
        LOGIN = 'login', 'Login'
        UI_LIBRARY = 'ui_library', 'UI library'
        BACKEND = 'backend', 'Backend API'
        API = 'api', 'API'
        ANALYTICS = 'analytics', 'Analytics'
        OTHER = 'other', 'Other'

    class Via(models.TextChoices):
        SOURCE = 'source', 'From source, at build'
        SYMLINK = 'symlink', 'Symlink'
        GIT = 'git', 'Git clone / deploy'
        CDN = 'cdn', 'CDN'
        URL = 'url', 'Own server URL'
        COPY = 'copy', 'Copy'
        PACKAGE = 'package', 'Package'
        API = 'api', 'API calls'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='dependencies')
    depends_on = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='dependents')
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    via = models.CharField(max_length=20, choices=Via.choices, blank=True)
    version = models.CharField(max_length=60, blank=True)          # @main, v1.6, a commit…
    reference = models.CharField(max_length=500, blank=True)       # the URL, path or remote used
    environment = models.ForeignKey(Environment, null=True, blank=True, on_delete=models.CASCADE,
                                    related_name='dependencies')
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['project__name', 'depends_on__name', 'environment__position']
        verbose_name_plural = 'dependencies'
        constraints = [
            models.UniqueConstraint(fields=['project', 'depends_on', 'environment'],
                                    name='unique_dependency_per_environment'),
            # SQLite treats NULLs as distinct: one project-wide row per pair, explicitly.
            models.UniqueConstraint(fields=['project', 'depends_on'],
                                    condition=models.Q(environment__isnull=True),
                                    name='unique_project_wide_dependency'),
        ]

    def __str__(self):
        return f'{self.project} → {self.depends_on}'


class Service(models.Model):
    """Third-party services projects use: Paddle, GitHub, an SMTP account, Iubenda…"""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    kind = models.CharField(max_length=60, blank=True)
    url = models.URLField(blank=True)
    # Which login or team it's under (an email, a team name): a pointer, never a password.
    account = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    projects = models.ManyToManyField(Project, blank=True, related_name='services')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Link(models.Model):
    """A labelled URL on a project or a platform (admin panels, docs, consoles…)."""

    label = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE,
                                related_name='links')
    platform = models.ForeignKey(Platform, null=True, blank=True, on_delete=models.CASCADE,
                                 related_name='links')
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.label


class GitHubProfile(models.Model):
    """The GitHub account the sync reads (a single row, filled by the sync)."""

    login = models.CharField(max_length=100)
    name = models.CharField(max_length=200, blank=True)
    bio = models.CharField(max_length=500, blank=True)
    avatar_url = models.URLField(max_length=500, blank=True)
    html_url = models.URLField(blank=True)
    blog = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=100, blank=True)
    company = models.CharField(max_length=100, blank=True)
    followers = models.PositiveIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)       # last successful sync
    attempted_at = models.DateTimeField(null=True, blank=True)    # last try, successful or not
    last_error = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.login
