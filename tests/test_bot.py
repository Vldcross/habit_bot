import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import DeleteWebhook, GetMe, GetWebhookInfo, SendMessage, SendPhoto
from aiogram.types import Message, Update, User, WebhookInfo

ROOT = Path(__file__).resolve().parents[1]
TEST_TOKEN = '123456:TEST_TOKEN_FOR_OFFLINE_TESTS_ONLY'


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.closed = False
        self.fail_photos = False
        self.webhook_url = ''
        self.on_send = None

    async def close(self):
        self.closed = True

    async def stream_content(self, *args, **kwargs):
        raise AssertionError('Unexpected download')
        yield b''

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name='Test', username='test_bot')
        if isinstance(method, GetWebhookInfo):
            return WebhookInfo(url=self.webhook_url, has_custom_certificate=False, pending_update_count=0)
        if isinstance(method, DeleteWebhook):
            self.webhook_url = ''
            return True
        if isinstance(method, SendPhoto) and self.fail_photos:
            raise TelegramBadRequest(method=method, message='photo unavailable')
        if isinstance(method, SendMessage) and self.on_send:
            self.on_send(method)
        if isinstance(method, (SendMessage, SendPhoto)):
            return Message(message_id=len(self.requests), date=0,
                           chat={'id': int(method.chat_id), 'type': 'private'},
                           text=getattr(method, 'text', None))
        raise AssertionError(f'Unexpected Telegram method: {type(method).__name__}')


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        spec = importlib.util.spec_from_file_location('habit_test_target', ROOT / 'bot.py')
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.app.DATA_FILE = Path(self.directory.name) / 'nested' / 'data.json'
        self.session = RecordingSession()
        self.bot = Bot(TEST_TOKEN, session=self.session)
        self.sequence = 0

    async def asyncTearDown(self):
        await self.bot.session.close()
        await self.app.dp.storage.close()

    async def send(self, text=None, user_id=123, chat_type='private'):
        self.sequence += 1
        update = Update(update_id=self.sequence,
                        message={'message_id': self.sequence, 'date': 0,
                                 'chat': {'id': user_id, 'type': chat_type},
                                 'from': {'id': user_id, 'is_bot': False, 'first_name': 'Test'},
                                 'text': text})
        await self.app.dp.feed_update(self.bot, update)

    def last_text(self):
        return next(method.text for method in reversed(self.session.requests)
                    if isinstance(method, SendMessage))

    async def test_start_creates_goal_and_preserves_progress_on_repeat(self):
        await self.send('/start')
        await self.send('Да')
        await self.send('/start')
        self.assertEqual(self.app.data['123']['saved'], 100)
        self.assertEqual(self.app.load_data(), self.app.data)

    async def test_unknown_user_and_non_text(self):
        await self.send(None)
        self.assertIn('/start', self.last_text())
        await self.send('/start')
        await self.send(None)
        self.assertIn('/help', self.last_text())

    async def test_group_messages_do_not_change_private_goals(self):
        await self.send('/start', chat_type='group')
        self.assertEqual(self.app.data, {})
        self.assertEqual(self.session.requests, [])

    async def test_settings_button_and_validated_values(self):
        await self.send('⚙️ Настройки')
        await self.send(None)
        self.assertIn('название', self.last_text())
        await self.send('Не курить')
        for value in ('0', '-10', '1.5', '1000001', 'abc', None):
            await self.send(value)
            self.assertIn('целая сумма', self.last_text())
        await self.send('250')
        for value in ('0', '-1', '3651', 'abc', None):
            await self.send(value)
            self.assertIn('целое число', self.last_text())
        await self.send('40')
        self.assertEqual(self.app.data['123'], dict(name='Не курить', amount=250,
                                                  days_done=0, total_days=40, saved=0))
        self.assertEqual(self.app.load_data(), self.app.data)

    async def test_settings_preserve_money_and_completed_date(self):
        await self.send('/start')
        await self.send('Да')
        completed = self.app.data['123']['last_completed_date']
        for text in ('/settings', 'Новая привычка', '300', '5'):
            await self.send(text)
        self.assertEqual(self.app.data['123']['saved'], 100)
        self.assertEqual(self.app.data['123']['last_completed_date'], completed)
        await self.send('Да')
        self.assertEqual(self.app.data['123']['saved'], 100)

    async def test_cancel_does_not_save_partial_settings(self):
        await self.send('/start')
        before = dict(self.app.data['123'])
        for text in ('/settings', 'Изменённая', '/cancel'):
            await self.send(text)
        self.assertEqual(self.app.load_data()['123'], before)
        await self.send('Да')
        self.assertEqual(self.app.data['123']['saved'], 100)

    async def test_repeated_yes_counts_once_per_moscow_day(self):
        await self.send('/start')
        with patch.object(self.app, 'today', return_value='2026-10-20'):
            await self.send('Да')
            await self.send('Да')
            self.assertIn('уже учтён', self.last_text())
            self.assertEqual(self.app.load_data()['123']['saved'], 100)
        with patch.object(self.app, 'today', return_value='2026-10-21'):
            await self.send('Да')
            self.assertEqual(self.app.data['123']['days_done'], 2)
            self.assertEqual(self.app.data['123']['saved'], 200)

    async def test_concurrent_yes_counts_once(self):
        await self.send('/start')
        await asyncio.gather(self.send('Да'), self.send('Да'))
        self.assertEqual(self.app.data['123']['saved'], 100)

    async def test_restart_preserves_daily_duplicate_protection(self):
        await self.send('/start')
        await self.send('Да')
        self.app.data.clear()
        self.app.data.update(self.app.load_data())
        await self.send('Да')
        self.assertEqual(self.app.data['123']['days_done'], 1)

    async def test_day_changes_at_moscow_midnight(self):
        from datetime import datetime, timezone
        instant = datetime(2026, 10, 20, 21, 30, tzinfo=timezone.utc)
        with patch.object(self.app, 'datetime') as clock:
            clock.now.side_effect = lambda tz: instant.astimezone(tz)
            self.assertEqual(self.app.today(), '2026-10-21')

    async def test_no_does_not_block_later_success(self):
        await self.send('/start')
        await self.send('Нет')
        self.assertEqual(self.app.data['123']['saved'], 0)
        await self.send('Да')
        self.assertEqual(self.app.data['123']['saved'], 100)

    async def test_finished_goal_stops_crediting(self):
        for text in ('/settings', 'Цель', '50', '1', 'Да'):
            await self.send(text)
        self.assertIn('цель достигнута', self.last_text())
        with patch.object(self.app, 'today', return_value='2099-01-01'):
            await self.send('Да')
        self.assertEqual(self.app.data['123']['saved'], 50)

    async def test_goal_length_cannot_be_below_progress(self):
        await self.send('/start')
        self.app.data['123']['days_done'] = 3
        for text in ('/settings', 'Привычка', '100', '2'):
            await self.send(text)
        self.assertIn('Уже отмечено 3', self.last_text())
        self.assertEqual(self.app.data['123']['total_days'], 30)

    async def test_statistics_and_help(self):
        await self.send('/start')
        await self.send('Да')
        await self.send('📊 Моя статистика')
        self.assertIn('1/30', self.last_text())
        self.assertIn('100 руб.', self.last_text())
        await self.send('/help')
        self.assertIn('/cancel', self.last_text())

    async def test_failed_photo_keeps_saved_progress(self):
        await self.send('/start')
        self.session.fail_photos = True
        await self.send('Да')
        self.assertEqual(self.app.load_data()['123']['saved'], 100)
        await self.send('📊 Моя статистика')
        self.assertIn('1/30', self.last_text())

    async def test_reset_removes_only_own_data_and_clears_settings(self):
        await self.send('/start', user_id=123)
        await self.send('/start', user_id=456)
        await self.send('/settings')
        await self.send('/reset_all')
        self.assertNotIn('123', self.app.load_data())
        self.assertIn('456', self.app.load_data())
        await self.send('Да')
        self.assertIn('/start', self.last_text())

    async def test_legacy_data_loads_without_losing_money(self):
        legacy = {'123': dict(name='Цель', amount=200, days_done=2, total_days=30, saved=400)}
        self.app.save_data(legacy)
        self.app.data.update(self.app.load_data())
        await self.send('Да')
        self.assertEqual(self.app.load_data()['123']['saved'], 600)

    async def test_corrupt_data_is_preserved(self):
        self.app.DATA_FILE.parent.mkdir()
        for content in ('{broken', '[]', '{"123": {"name": "bad"}}'):
            self.app.DATA_FILE.write_text(content)
            with self.assertRaisesRegex(RuntimeError, 'не перезаписаны'):
                self.app.load_data()
            self.assertEqual(self.app.DATA_FILE.read_text(), content)

    async def test_failed_write_preserves_file_and_in_memory_progress(self):
        await self.send('/start')
        before = self.app.DATA_FILE.read_bytes()
        with patch.object(self.app.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                await self.send('Да')
        self.assertEqual(self.app.DATA_FILE.read_bytes(), before)
        self.assertEqual(self.app.data['123']['saved'], 0)
        self.assertEqual(list(self.app.DATA_FILE.parent.iterdir()), [self.app.DATA_FILE])

    async def test_reminders_skip_completed_and_already_recorded_users(self):
        self.app.data.update({str(i): self.app.default_goal() for i in (1, 2, 3)})
        self.app.data['1']['last_completed_date'] = self.app.today()
        self.app.data['2']['days_done'] = 30
        await self.app.send_daily_reminder(self.bot)
        self.assertEqual([m.chat_id for m in self.session.requests], [3])

    async def test_reminders_survive_block_and_data_change(self):
        self.app.data.update({str(i): self.app.default_goal() for i in (1, 2, 3)})
        def on_send(method):
            if method.chat_id == 1:
                self.app.data.pop('2')
                raise TelegramForbiddenError(method=method, message='blocked')
        self.session.on_send = on_send
        await self.app.send_daily_reminder(self.bot)
        self.assertEqual([m.chat_id for m in self.session.requests], [1, 3])

    async def test_check_authenticates_without_polling_or_messages(self):
        self.session.webhook_url = 'https://example.com/existing-hook'
        with patch.dict(os.environ, BOT_TOKEN=TEST_TOKEN, RESET_WEBHOOK_ON_START='true'), \
                patch.object(self.app, 'ProxySession', return_value=self.session), \
                patch.object(self.app.dp, 'start_polling', new_callable=AsyncMock) as polling:
            await self.app.main(check=True)
            polling.assert_not_awaited()
        self.assertEqual([type(m) for m in self.session.requests], [GetMe])
        self.assertTrue(self.session.closed)

    async def test_polling_startup_and_shutdown(self):
        scheduler = MagicMock()
        with patch.dict(os.environ, BOT_TOKEN=TEST_TOKEN), \
                patch.object(self.app, 'ProxySession', return_value=self.session), \
                patch.object(self.app, 'AsyncIOScheduler', return_value=scheduler), \
                patch.object(self.app.dp, 'start_polling', new_callable=AsyncMock) as polling:
            await self.app.main()
            polling.assert_awaited_once()
        scheduler.start.assert_called_once()
        scheduler.shutdown.assert_called_once_with(wait=False)
        self.assertEqual(scheduler.add_job.call_args.kwargs['hour'], 21)
        self.assertTrue(self.session.closed)

    async def test_webhook_conflict_does_not_delete_webhook(self):
        self.session.webhook_url = 'https://example.com/existing-hook'
        with patch.dict(os.environ, BOT_TOKEN=TEST_TOKEN, RESET_WEBHOOK_ON_START=''), \
                patch.object(self.app, 'ProxySession', return_value=self.session):
            with self.assertRaisesRegex(RuntimeError, 'webhook'):
                await self.app.main()
        self.assertEqual([type(m) for m in self.session.requests], [GetMe, GetWebhookInfo])

    async def test_authorized_webhook_migration_preserves_pending_updates(self):
        self.session.webhook_url = 'https://example.com/old-hook'
        with patch.dict(os.environ, BOT_TOKEN=TEST_TOKEN, RESET_WEBHOOK_ON_START='true'), \
                patch.object(self.app, 'ProxySession', return_value=self.session), \
                patch.object(self.app, 'AsyncIOScheduler'), \
                patch.object(self.app.dp, 'start_polling', new_callable=AsyncMock) as polling:
            await self.app.main()
            polling.assert_awaited_once()
        deletion = next(method for method in self.session.requests if isinstance(method, DeleteWebhook))
        self.assertFalse(deletion.drop_pending_updates)
        self.assertEqual(self.session.webhook_url, '')

    async def test_failed_webhook_migration_does_not_start_polling(self):
        self.session.webhook_url = 'https://example.com/old-hook'
        original_request = self.session.make_request
        async def request(bot, method, timeout=None):
            if isinstance(method, DeleteWebhook):
                raise TelegramBadRequest(method=method, message='migration failed')
            return await original_request(bot, method, timeout)
        self.session.make_request = request
        with patch.dict(os.environ, BOT_TOKEN=TEST_TOKEN, RESET_WEBHOOK_ON_START='true'), \
                patch.object(self.app, 'ProxySession', return_value=self.session), \
                patch.object(self.app.dp, 'start_polling', new_callable=AsyncMock) as polling:
            with self.assertRaises(TelegramBadRequest):
                await self.app.main()
            polling.assert_not_awaited()
        self.assertTrue(self.session.closed)

    async def test_missing_token_has_actionable_error(self):
        with patch.dict(os.environ, BOT_TOKEN=''):
            with self.assertRaisesRegex(RuntimeError, 'BOT_TOKEN'):
                await self.app.main()

    async def test_logs_redact_token_in_urls_and_tracebacks(self):
        formatter = self.app.TokenRedactingFormatter('%(message)s')
        record = logging.LogRecord('test', logging.ERROR, '', 0,
                                   'Request https://api.telegram.org/bot%s/getMe', (TEST_TOKEN,), None)
        with patch.dict(os.environ, BOT_TOKEN=TEST_TOKEN):
            output = formatter.format(record)
        self.assertNotIn(TEST_TOKEN, output)
        self.assertIn('[BOT_TOKEN]', output)


if __name__ == '__main__':
    unittest.main()
