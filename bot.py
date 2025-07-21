import json
import logging
import os
import random
import aiohttp
import asyncio
from datetime import datetime
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
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Ошибка при сохранении данных: {e}")

users_data = load_data()
user_steps = {}
settings_steps = {}

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
            "reminder_hour": 21
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

def check_achievements(goal):
    if goal["progress"] == 7:
        return "🎉 Круто! Ты уже 7 дней держишься! Так держать!"
    elif goal["progress"] == 30:
        return "👑 Вау! 30 дней — ты мастер своей привычки!"
    return None

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    users_data[user_id] = {"goal": None, "reminder_hour": 21}
    save_data()
    intro_text = (
        "Привет! Я бот, который поможет тебе побеждать вредные привычки и копить деньги на свои мечты.

"
        "Как я работаю:
"
        "1. Ты задаёшь привычку, от которой хочешь избавиться.
"
        "2. Указываешь сумму, которую будешь откладывать за каждый день победы.
"
        "3. Я спрошу, достиг ли ты успеха сегодня, и если 'Да' — я добавлю сумму в твою копилку и пришлю котика 🐱.
"
        "4. Мы будем считать прогресс и накопленные деньги.

"
        "Команды:
"
        "/start — начать или настроить цель.
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
        "Вот что я могу:
"
        "/start — начать или изменить цель.
"
        "/settings — изменить параметры.
"
        "/reset_all — сбросить все данные.
"
        "/help — показать справку.
"
        "📊 Моя статистика — покажет текущий прогресс."
    )
    await message.answer(help_text)

@dp.message(Command("reset_all"))
async def reset_all_command(message: types.Message):
    user_id = str(message.from_user.id)
    users_data[user_id] = {"goal": None, "reminder_hour": 21}
    save_data()
    await message.answer("Все данные удалены. Можешь создать новую цель через /start.")

@dp.message(Command("settings"))
async def settings_command(message: types.Message):
    await message.answer("Выбери, что хочешь изменить:", reply_markup=settings_keyboard)

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

@dp.message(F.text)
async def onboarding_handler(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in user_steps:
        step_data = user_steps[user_id]
        step = step_data["step"]

        if step == "habit":
            step_data["goal"]["habit"] = message.text
            step_data["step"] = "amount"
            await message.answer("Сколько рублей ты готов откладывать каждый день?")
        elif step == "amount":
            try:
                amount = int(message.text)
                step_data["goal"]["amount"] = amount
                step_data["step"] = "goal_name"
                await message.answer(f"Ты готов откладывать {amount}₽ каждый день. Теперь напиши название своей цели.")
            except ValueError:
                await message.answer("Пожалуйста, введи сумму числом.")
        elif step == "goal_name":
            step_data["goal"]["name"] = message.text
            step_data["step"] = "days"
            await message.answer("Сколько дней ты хочешь держаться?")
        elif step == "days":
            try:
                days = int(message.text)
                step_data["goal"]["days"] = days
                step_data["step"] = "future_message"
                await message.answer("Напиши сообщение самому себе для будущего (когда достигнешь цели).")
            except ValueError:
                await message.answer("Пожалуйста, введи количество дней числом.")
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
{format_progress(users_data[user_id]['goal'])}
Мы начнём отслеживание с завтрашнего дня!",
                reply_markup=main_keyboard
            )
            user_steps.pop(user_id)

@dp.message(F.text.in_(["Да", "Нет"]))
async def daily_check(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    goal = user.get("goal")
    if not goal or not isinstance(goal, dict) or not all(k in goal for k in ['progress', 'saved', 'amount']):
        await message.answer("Сначала создай цель через /start.")
        return

    if message.text == "Да":
        goal["progress"] += 1
        goal["saved"] += goal["amount"]
        save_data()

        response = f"Отлично! {format_progress(goal)}"

        achievement = check_achievements(goal)
        if achievement:
            response += f"\n\n{achievement}"

        await message.answer(response)
        cat_url = await get_random_cat()
        if cat_url:
            await message.answer_photo(cat_url, caption="Твой котик за сегодняшний успех 🐱")

        if goal["progress"] >= goal["days"]:
            await message.answer(f"Поздравляю! Ты достиг цели: {goal['name']}!\n{goal['future_message']}")
    else:
        support_phrases = [
            "Сегодня не вышло, но завтра новый день. Ты справишься!",
            "Не переживай, главное — не останавливаться.",
            "Ничего, завтра получится лучше!"
        ]
        await message.answer(random.choice(support_phrases))

async def send_reminders():
    now_hour = datetime.now().hour
    for user_id, user_data in users_data.items():
        try:
            if user_data.get("reminder_hour", 21) == now_hour:
                await bot.send_message(user_id, "Сегодня ты победил привычку?", reply_markup=yes_no_keyboard)
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение {user_id}: {e}")

async def main():
    scheduler.add_job(send_reminders, "cron", hour=21, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
