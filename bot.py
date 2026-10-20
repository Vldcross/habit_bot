import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import random
import ssl
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import ClientSession, TCPConnector
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.token import TokenValidationError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

MOSCOW = ZoneInfo('Europe/Moscow')
DATA_FILE = Path(os.environ.get('DATA_FILE', Path(__file__).with_name('data.json')))
DAILY_HOUR = 21
logger = logging.getLogger(__name__)


class TokenRedactingFormatter(logging.Formatter):
    def format(self, record):
        rendered = super().format(record)
        token = os.environ.get('BOT_TOKEN', '').strip()
        return rendered.replace(token, '[BOT_TOKEN]') if token else rendered


class ProxySession(AiohttpSession):
    """Use the machine's HTTP proxy and CA trust without disabling TLS checks."""

    async def create_session(self):
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                trust_env=True,
                connector=TCPConnector(ssl=ssl.create_default_context()),
            )
        return self._session


class Settings(StatesGroup):
    name = State()
    amount = State()
    days = State()


def load_data():
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open(encoding='utf-8') as stream:
            result = json.load(stream)
        if not isinstance(result, dict):
            raise ValueError('Expected an object')
        for user_id, goal in result.items():
            if not isinstance(goal, dict):
                raise ValueError('Invalid goal')
            for key in ('amount', 'days_done', 'total_days', 'saved'):
                if type(goal.get(key)) is not int or goal[key] < 0:
                    raise ValueError('Invalid goal values')
            if not isinstance(goal.get('name'), str) or goal['total_days'] < 1:
                raise ValueError('Invalid goal settings')
            int(user_id)
        return result
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError(
            'Файл данных повреждён. Восстановите его из резервной копии; '
            'существующие данные не перезаписаны.'
        ) from exc


def save_data(updated):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=DATA_FILE.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(updated, stream, ensure_ascii=False, indent=4)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, DATA_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def default_goal():
    return dict(name='Вредная привычка', amount=100, days_done=0, total_days=30, saved=0)


data = {}
dp = Dispatcher(events_isolation=SimpleEventIsolation())
dp.message.filter(F.chat.type == 'private')
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text='📊 Моя статистика')],
        [KeyboardButton(text='Да'), KeyboardButton(text='Нет')],
        [KeyboardButton(text='⚙️ Настройки')],
    ],
    resize_keyboard=True,
)


def commit_goal(user_id, goal):
    updated = dict(data)
    updated[user_id] = goal
    save_data(updated)
    data.clear()
    data.update(updated)


def today():
    return datetime.now(MOSCOW).date().isoformat()


def format_progress(goal):
    return (
        f"Цель: {goal['name']}\n"
        f"Сумма за день: {goal['amount']} руб.\n"
        f"Дней достигнуто: {goal['days_done']}/{goal['total_days']}\n"
        f"Накоплено: {goal['saved']} руб."
    )


@dp.message(Command('start'))
async def start_command(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    if user_id not in data:
        commit_goal(user_id, default_goal())
    await message.answer(
        'Привет! Я помогу побеждать привычку и копить на цель.\n'
        'Открой ⚙️ Настройки, чтобы задать привычку, сумму и число дней.\n'
        'Каждый день в 21:00 по Москве я напомню о цели. '
        'Нажми «Да», если сегодня справился. Начисление — один раз в день.\n\n'
        '/settings — настройки\n/help — помощь\n'
        '/reset_all — удалить свою цель\n/cancel — отменить настройку\n'
        'Повторный /start сохраняет прогресс.',
        reply_markup=main_keyboard,
    )


@dp.message(Command('help'))
async def help_command(message: types.Message):
    await message.answer(
        '/start — начать или показать приветствие\n'
        '/settings — изменить привычку, сумму и число дней\n'
        '/cancel — отменить настройку\n/reset_all — удалить свою цель\n'
        '«Да» — отметить успешный день; «Нет» — оставить прогресс без изменений.\n'
        '«📊 Моя статистика» — посмотреть накопления. '
        'Напоминание приходит в 21:00 по Москве.',
    )


@dp.message(Command('cancel'))
async def cancel_settings(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer('Настройка отменена. Прогресс сохранён.', reply_markup=main_keyboard)


@dp.message(Command('reset_all'))
async def reset_all(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    if user_id not in data:
        await message.answer('У тебя нет активных целей. Нажми /start.')
        return
    updated = dict(data)
    del updated[user_id]
    save_data(updated)
    data.clear()
    data.update(updated)
    await message.answer('Все твои данные сброшены! Нажми /start, чтобы начать заново.')


@dp.message(Command('settings'))
@dp.message(F.text == '⚙️ Настройки')
async def settings_command(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Settings.name)
    await message.answer('Какую привычку хочешь победить? Введи название (до 100 символов).\n/cancel — отмена.')


@dp.message(Settings.name)
async def set_name(message: types.Message, state: FSMContext):
    name = (message.text or '').strip()
    if not name or len(name) > 100 or name.startswith('/'):
        await message.answer('Введи название от 1 до 100 символов или /cancel.')
        return
    await state.update_data(name=name)
    await state.set_state(Settings.amount)
    await message.answer('Сколько рублей откладывать за день? Введи целое число от 1 до 1 000 000.')


def positive_number(text, maximum):
    value = (text or '').strip()
    if not value.isascii() or not value.isdecimal() or len(value) > 10:
        return None
    number = int(value)
    return number if 1 <= number <= maximum else None


@dp.message(Settings.amount)
async def set_amount(message: types.Message, state: FSMContext):
    amount = positive_number(message.text, 1_000_000)
    if amount is None:
        await message.answer('Нужна целая сумма от 1 до 1 000 000 рублей.')
        return
    await state.update_data(amount=amount)
    await state.set_state(Settings.days)
    await message.answer('Сколько успешных дней нужно? Введи целое число от 1 до 3650.')


@dp.message(Settings.days)
async def set_days(message: types.Message, state: FSMContext):
    days = positive_number(message.text, 3650)
    if days is None:
        await message.answer('Нужно целое число от 1 до 3650.')
        return
    user_id = str(message.from_user.id)
    previous = data.get(user_id, default_goal())
    if days < previous['days_done']:
        await message.answer(
            f"Уже отмечено {previous['days_done']} дней. Выбери не меньше этого числа. "
            'Для новой цели сначала используй /cancel и /reset_all.',
        )
        return
    goal = dict(previous)
    goal.update(await state.get_data())
    goal['total_days'] = days
    commit_goal(user_id, goal)
    await state.clear()
    await message.answer('Настройки сохранены.\n' + format_progress(goal), reply_markup=main_keyboard)


async def send_cat_meme(bot: Bot, chat_id):
    photo = random.choice([
        'https://i.imgur.com/WxJ7d8C.jpeg',
        'https://i.imgur.com/9a5m3wP.jpeg',
        'https://i.imgur.com/J5jzF7H.jpeg',
    ])
    try:
        await bot.send_photo(chat_id, photo, caption='Молодец! Вот котик для настроения 🐱')
    except TelegramAPIError:
        logger.warning('Не удалось отправить картинку; прогресс сохранён.')


@dp.message()
async def handle_message(message: types.Message, bot: Bot):
    user_id = str(message.from_user.id)
    if user_id not in data:
        await message.answer('Нажми /start, чтобы задать цель.')
        return
    goal = data[user_id]
    if message.text == 'Да':
        if goal['days_done'] >= goal['total_days']:
            await message.answer('Цель уже достигнута! Для новой цели используй /reset_all и /start.')
            return
        current_day = today()
        if goal.get('last_completed_date') == current_day:
            await message.answer('Сегодняшний день уже учтён. Приходи завтра!')
            return
        updated = dict(goal)
        updated['days_done'] += 1
        updated['saved'] += goal['amount']
        updated['last_completed_date'] = current_day
        commit_goal(user_id, updated)
        text = 'Отлично! Прогресс обновлён.\n' + format_progress(updated)
        if updated['days_done'] == updated['total_days']:
            text += '\n🎉 Поздравляю, цель достигнута!'
        await message.answer(text)
        await send_cat_meme(bot, message.chat.id)
    elif message.text == 'Нет':
        await message.answer('Не сдавайся! Завтра будет новый шанс.')
    elif message.text == '📊 Моя статистика':
        await message.answer(format_progress(goal))
    else:
        await message.answer('Используй кнопки или /help.')


async def send_daily_reminder(bot: Bot):
    for user_id, goal in list(data.items()):
        if user_id not in data:
            continue
        goal = data[user_id]
        if goal['days_done'] >= goal['total_days'] or goal.get('last_completed_date') == today():
            continue
        try:
            await bot.send_message(int(user_id), 'Ты победил привычку сегодня?', reply_markup=main_keyboard)
        except TelegramForbiddenError:
            logger.info('Напоминание пропущено: бот недоступен пользователю.')
        except TelegramAPIError:
            logger.warning('Не удалось отправить напоминание; остальные пользователи будут обработаны.')


async def main(check=False):
    token = os.environ.get('BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Задайте BOT_TOKEN в секретах или переменных окружения. Не записывайте токен в код.')
    data.clear()
    data.update(load_data())
    scheduler = AsyncIOScheduler(timezone=MOSCOW)
    async with Bot(token=token, session=ProxySession()) as bot:
        identity = await bot.get_me()
        logger.info('Соединение с Telegram установлено: @%s', identity.username)
        if check:
            print('OK: Telegram getMe; данные загружены; сообщения не отправлялись.')
            return
        webhook = await bot.get_webhook_info()
        if webhook.url:
            if os.environ.get('RESET_WEBHOOK_ON_START', '').lower() != 'true':
                raise RuntimeError(
                    'У бота включён webhook. Для согласованного перехода на polling '
                    'задайте RESET_WEBHOOK_ON_START=true на новом хостинге.',
                )
            await bot.delete_webhook(drop_pending_updates=False)
            logger.info('Webhook отключён для перехода на polling; очередь обновлений сохранена.')
        scheduler.add_job(send_daily_reminder, 'cron', hour=DAILY_HOUR, minute=0,
                          kwargs={'bot': bot}, id='daily_reminder', replace_existing=True)
        scheduler.start()
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False)
        finally:
            scheduler.shutdown(wait=False)
            await asyncio.sleep(0)
            await dp.storage.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Бот привычек и накоплений')
    parser.add_argument('--check', action='store_true', help='Проверить доступ к Telegram без polling и сообщений')
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(TokenRedactingFormatter('%(levelname)s:%(name)s:%(message)s'))
    try:
        asyncio.run(main(check=options.check))
    except (RuntimeError, OSError, TelegramAPIError, TokenValidationError) as exc:
        if isinstance(exc, (RuntimeError, TokenValidationError)):
            logger.error('%s', exc)
        else:
            logger.error('Запуск не удался (%s). Проверьте сеть, BOT_TOKEN и доступ к файлу данных.', type(exc).__name__)
        raise SystemExit(1)
