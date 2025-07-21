import json
import logging
import os
import random
import aiohttp
import asyncio
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

API_TOKEN = "8015596815:AAEiisUZoMvVLoQ9r6ciC3KSwWwgrbv1EJE"
DATA_FILE = "data.json"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ---------------------- Работа с данными ----------------------
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка при загрузке данных: {e}")
            return {}
    return {}

def save_data():
    try:
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(users_data, f, ensure_ascii=False, indent=4)
        os.replace(temp_file, DATA_FILE)
    except Exception as e:
        logging.error(f"Ошибка при сохранении данных: {e}")

users_data = load_data()
user_steps = {}

# ---------------------- Клавиатуры ----------------------
yes_no_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
    resize_keyboard=True
)

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Моя статистика")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="❌ Сбросить всё")]
    ],
    resize_keyboard=True
)

settings_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Изменить привычку")],
        [KeyboardButton(text="Изменить сумму")],
        [KeyboardButton(text="Изменить количество дней")],
        [KeyboardButton(text="Изменить сообщение для будущего")],
        [KeyboardButton(text="Изменить время напоминаний")],
        [KeyboardButton(text="↩️ Ничего не менять")]
    ],
    resize_keyboard=True
)

# ---------------------- Вспомогательные функции ----------------------
async def get_random_cat():
    url = "https://api.thecatapi.com/v1/images/search"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return data[0]["url"] if data else None
    except Exception as e:
        logging.error(f"Ошибка при получении котика: {e}")
        return None

def get_user(user_id):
    user_id = str(user_id)
    if user_id not in users_data:
        users_data[user_id] = {
            "goal": None,
            "reminder_hour": 21,
            "last_check_date": ""
        }
        save_data()
    return users_data[user_id]

def format_progress(goal):
    return (
        f"Цель: {goal.get('name', '-')}
"
        f"Привычка: {goal.get('habit', '-')}
"
        f"Прогресс: {goal.get('progress', 0)}/{goal.get('days', 0)} дней
"
        f"Накоплено: {goal.get('saved', 0)}₽"
    )

# ---------------------- Команды ----------------------
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    users_data[user_id] = {"goal": None, "reminder_hour": 21, "last_check_date": ""}
    save_data()
    intro_text = (
        "Привет! Я бот, который поможет тебе побеждать вредные привычки и копить деньги на свои мечты.

"
        "Как я работаю:
"
        "1. Ты задаёшь привычку.
"
        "2. Указываешь сумму, которую будешь откладывать за каждый день победы.
"
        "3. Я каждый день спрошу, достиг ли ты успеха, и если 'Да', добавлю сумму в копилку и пришлю котика 🐱.

"
        "Команды:
"
        "/start — начать или изменить цель.
"
        "/settings — изменить цель или настройки.
"
        "/help — показать команды.
"
        "/reset_all — сбросить все данные.
"
    )
    await message.answer(intro_text)
    await message.answer("Давай начнём! Напиши свою привычку.", reply_markup=types.ReplyKeyboardRemove())
    user_steps[user_id] = {"step": "habit", "goal": {}}

@dp.message(Command("help"))
async def help_command(message: types.Message):
    help_text = (
        "Что я умею:
"
        "/start — начать или изменить цель.
"
        "/settings — изменить параметры.
"
        "/reset_all — сбросить данные.
"
        "📊 Моя статистика — прогресс по цели."
    )
    await message.answer(help_text)

@dp.message(Command("reset_all"))
async def reset_all_command(message: types.Message):
    user_id = str(message.from_user.id)
    users_data[user_id] = {"goal": None, "reminder_hour": 21, "last_check_date": ""}
    save_data()
    await message.answer("Все данные удалены. Создай новую цель через /start.")

@dp.message(Command("settings"))
async def settings_command(message: types.Message):
    await message.answer("Выбери, что хочешь изменить:", reply_markup=settings_keyboard)

# ---------------------- Кнопки ----------------------
@dp.message(F.text == "📊 Моя статистика")
async def show_stats(message: types.Message):
    user = get_user(str(message.from_user.id))
    goal = user.get("goal")
    if goal:
        await message.answer(format_progress(goal))
    else:
        await message.answer("Цель ещё не создана. Используй /start.")

@dp.message(F.text == "↩️ Ничего не менять")
async def no_changes(message: types.Message):
    await message.answer("Ок, ничего не меняем.", reply_markup=main_keyboard)

# ---------------------- Онбординг ----------------------
@dp.message(F.text)
async def onboarding_handler(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in user_steps:
        step_data = user_steps[user_id]
        step = step_data["step"]

        if step == "habit":
            step_data["goal"]["habit"] = message.text
            step_data["step"] = "amount"
            await message.answer("Сколько рублей откладывать каждый день?")
        elif step == "amount":
            try:
                amount = int(message.text)
                step_data["goal"]["amount"] = amount
                step_data["step"] = "goal_name"
                await message.answer(f"Будем откладывать {amount}₽. Теперь напиши название своей цели.")
            except ValueError:
                await message.answer("Введи сумму числом.")
        elif step == "goal_name":
            step_data["goal"]["name"] = message.text
            step_data["step"] = "days"
            await message.answer("Сколько дней хочешь держаться?")
        elif step == "days":
            try:
                days = int(message.text)
                step_data["goal"]["days"] = days
                step_data["step"] = "future_message"
                await message.answer("Напиши сообщение самому себе в будущее.")
            except ValueError:
                await message.answer("Введи число.")
        elif step == "future_message":
            step_data["goal"]["future_message"] = message.text
            users_data[user_id]["goal"] = {
                **step_data["goal"],
                "progress": 0,
                "saved": 0
            }
            save_data()
            await message.answer(
                f"Отлично! Вот твоя цель:
{format_progress(users_data[user_id]['goal'])}",
                reply_markup=main_keyboard
            )
            user_steps.pop(user_id)

# ---------------------- Проверка привычки ----------------------
@dp.message(F.text.in_(["Да", "Нет"]))
async def daily_check(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    goal = user.get("goal")
    today = str(date.today())

    if not goal or not all(k in goal for k in ['progress', 'saved', 'amount']):
        await message.answer("Сначала создай цель через /start.")
        return

    if user.get("last_check_date") == today:
        await message.answer("Сегодня ты уже ответил!")
        return

    if message.text == "Да":
        goal["progress"] += 1
        goal["saved"] += goal["amount"]
        user["last_check_date"] = today
        save_data()

        response = f"Отлично! {format_progress(goal)}"
        await message.answer(response)
        cat_url = await get_random_cat()
        if cat_url:
            await message.answer_photo(cat_url, caption="Котик за твой успех 🐱")

        if goal["progress"] >= goal["days"]:
            await message.answer(f"Поздравляю! Цель {goal['name']} достигнута!
{goal['future_message']}")
    else:
        user["last_check_date"] = today
        save_data()
        await message.answer("Сегодня не получилось, но завтра будет лучше!")

# ---------------------- Напоминания ----------------------
async def send_reminders():
    now = datetime.now()
    for user_id, user_data in users_data.items():
        try:
            if user_data.get("reminder_hour", 21) == now.hour and now.minute == 0:
                await bot.send_message(user_id, "Сегодня ты победил привычку?", reply_markup=yes_no_keyboard)
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение {user_id}: {e}")

# ---------------------- Main ----------------------
async def main():
    scheduler.add_job(send_reminders, "cron", minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
