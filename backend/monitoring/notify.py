"""Notifications: a message when a red "needs attention" item appears, and when it clears.

After each run the worker compares the red (danger) items with the ones already announced
(MonitorState.notified) and sends one message with what's new and what's resolved, through
every channel configured in .env: Telegram, email, or both. Warnings and info items are
only on the Status page.

With no channel configured nothing is recorded either, so the first message after setting
one up lists everything red at that moment. The "health checks have stopped" item is never
sent: the worker that would send it is the one that stopped.
"""
import logging

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from . import attention
from .models import MonitorState

log = logging.getLogger('gateway.notify')
TELEGRAM_API = 'https://api.telegram.org'
TIMEOUT = 15
NOT_SENT = {'worker:stopped'}
# Events rather than problems (monitoring/local.py, security_attention): red for a day after
# they happen, and each new one is announced, but their ageing out isn't news.
QUIET_WHEN_CLEARED = ('security:sudo:', 'security:container:', 'security:ssh-password:', 'security:ssh-root:')


class NotifyError(Exception):
    pass


def channels():
    """The channels configured in .env."""
    out = []
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        out.append('telegram')
    if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD and settings.NOTIFY_EMAIL_TO:
        out.append('email')
    return out


def telegram(method, payload=None):
    """Call the Telegram bot API. Errors never include the URL: it contains the token."""
    try:
        resp = requests.post(f'{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}',
                             json=payload or {}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise NotifyError(f'Telegram is unreachable ({e.__class__.__name__})') from None
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not resp.ok or not body.get('ok'):
        raise NotifyError(f'Telegram answered {resp.status_code}: {body.get("description", "")}'.rstrip(': '))
    return body.get('result')


def send_telegram(subject, text):
    telegram('sendMessage', {'chat_id': settings.TELEGRAM_CHAT_ID, 'text': f'{subject}\n\n{text}',
                             'disable_web_page_preview': True})


def send_email(subject, text):
    try:
        send_mail(subject, text, settings.DEFAULT_FROM_EMAIL, settings.NOTIFY_EMAIL_TO)
    except Exception as e:      # smtplib and socket errors (their text never holds the password)
        raise NotifyError(f'Email failed ({e.__class__.__name__}: {str(e)[:150]})') from None


SENDERS = {'telegram': send_telegram, 'email': send_email}


def send(subject, text, only=None):
    """Send through each channel. Returns {channel: '' when sent, or the error}."""
    results = {}
    for channel in only or channels():
        try:
            SENDERS[channel](subject, text)
            results[channel] = ''
        except NotifyError as e:
            results[channel] = str(e)
            log.error('Notification by %s failed: %s', channel, e)
    return results


def compose(new, resolved):
    """(subject, text) for the red items that appeared and the titles of those that cleared."""
    counts = ([f'{len(new)} new problem' + ('s' if len(new) > 1 else '')] if new else []) + \
             ([f'{len(resolved)} resolved'] if resolved else [])
    lines = []
    if new:
        lines.append('Needs attention:')
        for item in new:
            lines.append(f'• {item["title"]}')
            if item['detail']:
                lines.append(f'  {item["detail"]}')
    if resolved:
        lines += ([''] if lines else []) + ['Resolved:'] + [f'• {title}' for title in resolved]
    if settings.SITE_URL:
        lines += ['', f'{settings.SITE_URL}/status']
    return f'Projects Gateway: {", ".join(counts)}', '\n'.join(lines)


def notify(now=None):
    """Announce what turned red or cleared since the last message. Returns what was sent, or None."""
    now = now or timezone.now()
    configured = channels()
    if not configured:
        return None
    state = MonitorState.get()
    current = {i['key']: i for i in attention.items(now) if i['severity'] == 'danger' and i['key'] not in NOT_SENT}
    new = [item for key, item in current.items() if key not in state.notified]
    resolved = [title for key, title in state.notified.items()
                if key not in current and not key.startswith(QUIET_WHEN_CLEARED)]
    if not new and not resolved:
        return None
    subject, text = compose(new, resolved)
    results = send(subject, text, configured)
    errors = [error for error in results.values() if error]
    # Delivered through at least one channel: don't send it again. None got it: retry next run.
    if len(errors) < len(results):
        state.notified = {key: item['title'] for key, item in current.items()}
        state.notify_sent_at = now
    state.notify_error = '; '.join(errors)[:300]
    state.save(update_fields=['notified', 'notify_sent_at', 'notify_error'])
    return {'subject': subject, 'results': results}
