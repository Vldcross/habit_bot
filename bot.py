
import json
import logging
import os
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

API_TOKEN = "8015596815:AAEiisUZoMvVLoQ9r6ciC3KSwWwgrbv1EJE"
DATA_FILE = "data.json"
DAILY_HOUR = 21  # 21:00 по МСК

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data):
    temp_file = DATA_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(temp_file, DATA_FILE)


data = load_data()

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Моя статистика")],
        [KeyboardButton(text="Да"), KeyboardButton(text="Нет")],
        [KeyboardButton(text="⚙️ Настройки")]
    ],
    resize_keyboard=True
)


async def send_cat_meme(chat_id):
    cat_memes = [
        "https://i.imgur.com/WxJ7d8C.jpeg",
        "https://i.imgur.com/9a5m3wP.jpeg",
        "https://i.imgur.com/J5jzF7H.jpeg"
    ]
    meme_url = random.choice(cat_memes)
    await bot.send_photo(chat_id, meme_url, caption="Молодец! Вот котик для настроения 🐱")


def format_progress(goal):
    return (
        "Цель: {0}\nСумма за день: {1} руб.\nДней достигнуто: {2}/{3}\nНакоплено: {4} руб."
        .format(
            goal.get('name', '-'),
            goal.get('amount', 0),
            goal.get('days_done', 0),
            goal.get('total_days', 0),
            goal.get('saved', 0)
        )
    )


@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in data:
        data[user_id] = {
            "name": "Вредная привычка",
            "amount": 100,
            "days_done": 0,
            "total_days": 30,
            "saved": 0
        }
        save_data(data)

    intro_text = (
        "Привет! Я бот, который поможет тебе побеждать вредные привычки и копить деньги на свои мечты.\n\n"
        "Как я работаю:\n"
        "1. Ты задаёшь привычку.\n"
        "2. Указываешь сумму, которую будешь откладывать за каждый день победы.\n"
        "3. Каждый день я спрошу: 'Ты победил привычку сегодня?'\n"
        "4. Если 'Да', я добавлю сумму в копилку и пришлю котика 🐱.\n\n"
        "Команды:\n"
        "/start — начать заново.\n"
        "/settings — изменить цель или настройки.\n"
        "/help — показать команды.\n"
        "/reset_all — сбросить все данные."
    )

    await message.answer(intro_text, reply_markup=main_keyboard)


@dp.message(Command("help"))
async def help_command(message: types.Message):
    help_text = (
        "Доступные команды:\n"
        "/start — перезапустить бота.\n"
        "/settings — изменить цель, сумму, дни.\n"
        "/reset_all — сбросить все данные.\n"
        "Кнопки 'Да' и 'Нет' помогают отмечать прогресс."
    )
    await message.answer(help_text)


@dp.message(Command("reset_all"))
async def reset_all(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in data:
        del data[user_id]
        save_data(data)
        await message.answer("Все данные сброшены! Нажми /start, чтобы начать заново.")
    else:
        await message.answer("У тебя нет активных целей.")


@dp.message()
async def handle_message(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in data:
        await message.answer("Нажми /start, чтобы задать цель.")
        return

    goal = data[user_id]
    if message.text == "Да":
        goal["days_done"] += 1
        goal["saved"] += goal["amount"]
        save_data(data)
        await message.answer("Отлично! Прогресс обновлён.")
        await send_cat_meme(user_id)
    elif message.text == "Нет":
        await message.answer("Не сдавайся! Завтра будет новый шанс.")
    elif message.text == "📊 Моя статистика":
        await message.answer(format_progress(goal))
    else:
        await message.answer("Я не понял команду. Используй кнопки или /help.")


async def send_daily_reminder():
    for user_id in data:
        try:
            await bot.send_message(user_id, "Ты победил привычку сегодня?", reply_markup=main_keyboard)
        except Exception as e:
            logging.error(f"Ошибка при отправке напоминания {user_id}: {e}")


def schedule_jobs():
    scheduler.add_job(send_daily_reminder, "cron", hour=DAILY_HOUR)
    scheduler.start()


async def main():
    schedule_jobs()
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
