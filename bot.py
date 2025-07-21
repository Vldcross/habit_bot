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

# --- Вставлен токен бота ---
API_TOKEN = "8015596815:AAEiisUZoMvVLoQ9r6ciC3KSwWwgrbv1EJE"
DATA_FILE = "data.json"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ---------------------- ДАННЫЕ ----------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=4)

users_data = load_data()
user_steps = {}

# ---------------------- КЛАВИАТУРЫ ----------------------
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

# ---------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------------
async def get_random_cat():
    url = "https://api.thecatapi.com/v1/images/search"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return data[0]["url"] if data else None
    except Exception as e:
        logging.error(f"Ошибка при получении мема: {e}")
        return None

def get_user(user_id):
    user_id = str(user_id)
    if user_id not in users_data:
        users_data[user_id] = {
            "goals": [],
            "reminder_hour": 21
        }
        save_data()
    return users_data[user_id]

# ---------------------- КОМАНДЫ ----------------------
@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    users_data[user_id] = {"goals": [], "reminder_hour": 21}
    save_data()
    await message.answer("Привет! Давай настроим твою первую цель. Напиши свою привычку.", reply_markup=types.ReplyKeyboardRemove())
    user_steps[user_id] = {"step": "habit", "goal": {}}

@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "/start - начать онбординг\n"
        "/settings - изменить цели или параметры\n"
        "/help - помощь по командам\n"
        "/reset_all - сбросить все цели и данные\n"
        "📊 Моя статистика - показывает текущие цели и прогресс."
    )

@dp.message(Command("reset_all"))
async def reset_all_command(message: types.Message):
    user_id = str(message.from_user.id)
    users_data[user_id] = {"goals": [], "reminder_hour": 21}
    save_data()
    await message.answer("Все твои данные удалены. Можешь начать заново с /start.")

@dp.message(Command("settings"))
async def settings_command(message: types.Message):
    await message.answer("⚙️ Выбери, что хочешь изменить:", reply_markup=main_keyboard)

# ---------------------- ОБРАБОТКА ОНБОРДИНГА ----------------------
@dp.message(F.text)
async def onboarding_handler(message: types.Message):
    if message.text.startswith('/'):
        return
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
                await message.answer(f"Ты готов откладывать {amount}₽ каждый день. Теперь напиши цель.")
            except ValueError:
                await message.answer("Введи сумму числом.")
        elif step == "goal_name":
            step_data["goal"]["name"] = message.text
            step_data["step"] = "days"
            await message.answer("Сколько дней ты хочешь продержаться?")
        elif step == "days":
            try:
                days = int(message.text)
                step_data["goal"]["days"] = days
                step_data["step"] = "future_message"
                await message.answer("Напиши сообщение самому себе для будущего.")
            except ValueError:
                await message.answer("Введи количество дней числом.")
        elif step == "future_message":
            step_data["goal"]["future_message"] = message.text
            user = get_user(user_id)
            if len(user["goals"]) >= 3:
                await message.answer("У тебя уже 3 цели. Сначала удали одну из них в /settings.")
                user_steps.pop(user_id)
                return
            user["goals"].append({
                **step_data["goal"],
                "progress": 0,
                "saved": 0
            })
            save_data()
            await message.answer(
                f"Супер! Твоя цель: {step_data['goal']['name']}\n"
                f"Привычка: {step_data['goal']['habit']}\n"
                f"Сумма: {step_data['goal']['amount']}₽\n"
                f"Длительность: {step_data['goal']['days']} дней\n"
                f"Уже завтра мы начнем!"
            )
            user_steps.pop(user_id)

# ---------------------- НАПОМИНАНИЯ ----------------------
async def send_reminders():
    now_hour = datetime.now().hour
    for user_id, user_data in users_data.items():
        try:
            if user_data.get("reminder_hour", 21) == now_hour:
                await bot.send_message(user_id, "Ты сегодня победил свою привычку?", reply_markup=yes_no_keyboard)
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение {user_id}: {e}")

# ---------------------- ДЕЙСТВИЯ ПОЛЬЗОВАТЕЛЯ ----------------------
@dp.message(F.text.in_(["Да", "Нет"]))
async def daily_check(message: types.Message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    if not user["goals"]:
        await message.answer("У тебя пока нет целей. Начни с /start.")
        return

    current_goal = user["goals"][0]

    if message.text == "Да":
        current_goal["progress"] += 1
        current_goal["saved"] += current_goal["amount"]
        save_data()

        await message.answer(
            f"Ты красавчик! Прогресс: {current_goal['progress']}/{current_goal['days']} дней, накоплено {current_goal['saved']}₽."
        )

        cat_url = await get_random_cat()
        if cat_url:
            await message.answer_photo(cat_url, caption="Твой мем с котиком! 🐱")

        if current_goal["progress"] >= current_goal["days"]:
            await message.answer(f"Поздравляю! Ты достиг цели: {current_goal['name']}!\n{current_goal['future_message']}")
    else:
        support_phrases = [
            "Не беда, завтра новый день!",
            "Ты сможешь! Отдыхай и набирайся сил.",
            "Все ок, котик ждёт твоей победы завтра!"
        ]
        await message.answer(random.choice(support_phrases))

# ---------------------- MAIN ----------------------
async def main():
    scheduler.add_job(send_reminders, "cron", hour=21, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
