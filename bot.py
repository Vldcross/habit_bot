import json
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

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
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

data = load_data()
yes_no_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
yes_no_keyboard.add(KeyboardButton("Да"), KeyboardButton("Нет"))

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in data:
        data[user_id] = {
            "habit": None,
            "daily_amount": 0,
            "goal": None,
            "goal_days": 0,
            "current_day": 0,
            "saved_amount": 0
        }
        save_data(data)
        await message.answer("Привет! От какой привычки хочешь избавиться?")
    else:
        await message.answer("Привет снова! Я уже всё помню 😉")

@dp.message(F.text, lambda m: str(m.from_user.id) in data and data[str(m.from_user.id)]["habit"] is None)
async def set_habit(message: types.Message):
    user_id = str(message.from_user.id)
    data[user_id]["habit"] = message.text
    save_data(data)
    await message.answer(f"Отлично! Сколько рублей ты готов откладывать каждый день, если победишь привычку '{message.text}'?")

@dp.message(F.text, lambda m: str(m.from_user.id) in data and data[str(m.from_user.id)]["daily_amount"] == 0 and data[str(m.from_user.id)]["habit"] is not None)
async def set_amount(message: types.Message):
    user_id = str(message.from_user.id)
    try:
        amount = int(message.text)
        data[user_id]["daily_amount"] = amount
        save_data(data)
        await message.answer("Супер! А теперь напиши свою цель (например, PlayStation 5).")
    except:
        await message.answer("Пожалуйста, введи число.")

@dp.message(F.text, lambda m: str(m.from_user.id) in data and data[str(m.from_user.id)]["goal"] is None and data[str(m.from_user.id)]["daily_amount"] > 0)
async def set_goal(message: types.Message):
    user_id = str(message.from_user.id)
    data[user_id]["goal"] = message.text
    save_data(data)
    await message.answer("Сколько дней ты хочешь работать над этой целью?")

@dp.message(F.text, lambda m: str(m.from_user.id) in data and data[str(m.from_user.id)]["goal_days"] == 0 and data[str(m.from_user.id)]["goal"] is not None)
async def set_goal_days(message: types.Message):
    user_id = str(message.from_user.id)
    try:
        days = int(message.text)
        data[user_id]["goal_days"] = days
        save_data(data)
        await message.answer(f"Отлично! Каждый день в 21:00 я буду спрашивать, победил ли ты привычку '{data[user_id]['habit']}'. Готов?", reply_markup=yes_no_keyboard)
    except:
        await message.answer("Пожалуйста, введи число.")

@dp.message(F.text.in_(["Да", "Нет"]))
async def daily_check(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in data or data[user_id]["habit"] is None:
        await message.answer("Сначала введи свои данные через /start")
        return

    if message.text == "Да":
        data[user_id]["current_day"] += 1
        data[user_id]["saved_amount"] += data[user_id]["daily_amount"]
        save_data(data)
        await message.answer(f"Ты красавчик! 💪 Ты уже ближе к своей цели: {data[user_id]['goal']}, "
                             f"ты продержался {data[user_id]['current_day']}/{data[user_id]['goal_days']} дней, "
                             f"и накопил аж целых {data[user_id]['saved_amount']}₽.")
    else:
        await message.answer(f"Очень жаль, котичка. 😿 Завтра будет новый шанс! "
                             f"Сейчас {data[user_id]['current_day']}/{data[user_id]['goal_days']} дней, "
                             f"в копилке {data[user_id]['saved_amount']}₽.")

async def send_daily_reminder():
    for user_id in data.keys():
        try:
            await bot.send_message(user_id, f"Ты сегодня победил свою привычку — {data[user_id]['habit']}?", reply_markup=yes_no_keyboard)
        except Exception as e:
            logging.warning(f"Не смог отправить сообщение пользователю {user_id}: {e}")

async def main():
    scheduler.add_job(send_daily_reminder, "cron", hour=DAILY_HOUR, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
