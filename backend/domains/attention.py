"""The domains' part of "Needs attention" (see monitoring/attention.py).

A domain on auto-renew is only flagged once its date has passed: the registry shows the
new date a day or so after the renewal. Without auto-renew: from 30 days before, red (and
notified) in the last 7.
"""
from django.utils import timezone

from .models import Domain
from .registry import days_left

WARN_DAYS = 30
DANGER_DAYS = 7


def attention(add, today=None):
    today = today or timezone.localdate()
    unknown, unreadable = [], []
    for d in Domain.objects.all():
        left = days_left(d.expires_on, today)
        when = d.expires_on.strftime('%d %b %Y') if d.expires_on else ''
        if left is None:
            unknown.append(d.name)
        elif left < 0:
            add(f'domain:{d.name}', 'domain', 'danger', f'Domain expired: {d.name}',
                f'On {when}.' + (' Auto-renew is on, but the registry still shows that date.' if d.auto_renew else ''),
                page='domains')
        elif not d.auto_renew and left < WARN_DAYS:
            add(f'domain:{d.name}', 'domain', 'danger' if left < DANGER_DAYS else 'warning',
                f'Domain expires: {d.name}', f'On {when} ({left} days left); auto-renew is off.', page='domains')
        if d.lookup_error and not d.expires_by_hand and d.expires_on is not None:
            unreadable.append(d.name)
    if unknown:
        add('domains:unknown', 'domain', 'info', 'Domains with no expiry date',
            f'{", ".join(unknown)}: their registry doesn’t publish it, enter it by hand.', page='domains')
    if unreadable:
        add('domains:lookup', 'domain', 'info', 'Domains the registry didn’t answer for',
            f'{", ".join(unreadable)}: the dates shown are from an earlier lookup.', page='domains')
