"""Send a test notification through every configured channel, and help set Telegram up.

With TELEGRAM_BOT_TOKEN set but no TELEGRAM_CHAT_ID yet, it prints the chats that have
written to the bot (send it any message first): put your chat's id in .env.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from monitoring import notify


class Command(BaseCommand):
    help = 'Send a test notification (and find your Telegram chat ID).'

    def handle(self, *args, **options):
        if settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_CHAT_ID:
            self.telegram_chats()
        configured = notify.channels()
        if not configured:
            self.stdout.write('No channel is configured yet: see the notification settings in .env.example.')
            return
        results = notify.send('Projects Gateway: test',
                              f'This is a test. Real messages come when something turns red.\n\n{settings.SITE_URL}/status',
                              configured)
        for channel, error in results.items():
            if error:
                self.stdout.write(self.style.ERROR(f'{channel}: {error}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'{channel}: sent'))

    def telegram_chats(self):
        try:
            updates = notify.telegram('getUpdates')
        except notify.NotifyError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return
        chats = {}
        for update in updates or []:
            message = update.get('message') or update.get('channel_post') or {}
            chat = message.get('chat') or {}
            if 'id' in chat:
                chats[chat['id']] = chat.get('username') or chat.get('title') or chat.get('first_name') or ''
        if not chats:
            self.stdout.write('TELEGRAM_CHAT_ID is empty, and nobody has written to the bot yet: '
                              'send it any message in Telegram, then run this again.')
            return
        self.stdout.write('TELEGRAM_CHAT_ID is empty. Chats that wrote to the bot:')
        for chat_id, name in chats.items():
            self.stdout.write(f'  {chat_id}  {name}')
        self.stdout.write('Put yours in .env as TELEGRAM_CHAT_ID, then run this again.')
