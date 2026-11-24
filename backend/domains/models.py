"""The domains I own (or renew for a client): registrar, DNS, expiry, and what uses them.

Which projects and sites use a domain is derived from the catalog's URLs (any host equal
to it or under it); `projects` adds the links no URL shows (a redirect, a parked name).
The registry fills the expiry, registrar, nameservers and status once a day (RDAP, or
WHOIS for .it); for endings that publish no expiry (.eu, .es) it's typed by hand.

Where a domain is renewed and where its DNS zone is edited are Services (the account
they're under is the point); `registrar` and `dns_provider` keep what the registry says
and what its nameservers suggest, and an empty link is filled from them when a Service's
name matches.
"""
from django.db import models

from catalog.models import Client, Project, Service


def matching_service(text, services):
    """The Service whose name appears in `text` ("Aruba" in "Aruba S.p.A."), the longest
    such name, or None. Names under 3 letters never match. A name only matches when the
    whole of it appears, so "Example SMTP (no-reply@…)" isn't taken for "EXAMPLE, Inc."."""
    text = (text or '').lower()
    best = None
    for service in services:
        name = service.name.strip().lower()
        if len(name) >= 3 and name in text and (best is None or len(name) > len(best.name.strip())):
            best = service
    return best


class Domain(models.Model):
    name = models.CharField(max_length=253, unique=True)   # the registered name, lowercase: example.com
    registrar = models.CharField(max_length=100, blank=True)      # what the registry says
    dns_provider = models.CharField(max_length=100, blank=True)   # guessed from the nameservers
    # Where it's renewed, and where its DNS zone is edited.
    registrar_service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.SET_NULL,
                                          related_name='registered_domains')
    dns_service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='dns_domains')
    # Whose it is when I renew it for a client (blank: mine).
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL, related_name='domains')
    projects = models.ManyToManyField(Project, blank=True, related_name='domains')
    auto_renew = models.BooleanField(default=False)
    expires_on = models.DateField(null=True, blank=True)
    # The date was typed: the registry doesn't publish one (.eu, .es), so lookups leave it.
    expires_by_hand = models.BooleanField(default=False)
    registered_on = models.DateField(null=True, blank=True)
    nameservers = models.JSONField(default=list, blank=True)
    registry_status = models.JSONField(default=list, blank=True)
    looked_up_at = models.DateTimeField(null=True, blank=True)
    lookup_error = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def covers(self, host):
        host = (host or '').lower().rstrip('.')
        return host == self.name or host.endswith('.' + self.name)

    def link_services(self, services=None):
        """Fill an empty registrar or DNS link from the registry's text, when a Service's
        name matches. A link already set (by hand or before) is never changed."""
        services = list(Service.objects.all()) if services is None else services
        if self.registrar_service_id is None:
            self.registrar_service = matching_service(self.registrar, services)
        if self.dns_service_id is None:
            self.dns_service = matching_service(self.dns_provider, services)
