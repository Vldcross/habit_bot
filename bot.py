import json
import logging
import os
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
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
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

data = load_data()

yes_no_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
    resize_keyboard=True
)

settings_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎯 Изменить цель"), KeyboardButton(text="💰 Изменить сумму")],
        [KeyboardButton(text="⏰ Изменить время"), KeyboardButton(text="📅 Изменить дни")],
        [KeyboardButton(text="📊 Моя статистика")],
        [KeyboardButton(text="⚙️ Сбросить цель")],
        [KeyboardButton(text="↩️ Ничего не менять")]
    ],
    resize_keyboard=True
)

awaiting_action = {}
pending_changes = {}

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
            "saved_amount": 0,
            "reminder_hour": DAILY_HOUR
        }
        save_data(data)
        await message.answer("Привет! От какой привычки хочешь избавиться?")
    else:
        await message.answer("Привет снова! Используй /settings, чтобы изменить данные.")

@dp.message(Command("settings"))
async def show_settings(message: types.Message):
    await message.answer("Выбери, что хочешь изменить:", reply_markup=settings_keyboard)

@dp.message(F.text == "📊 Моя статистика")
async def show_stats(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in data or data[user_id]["goal"] is None:
        await message.answer("У тебя пока нет цели. Используй /start, чтобы начать.")
        return
    habit = data[user_id].get("habit", "—")
    goal = data[user_id].get("goal", "—")
    days = data[user_id].get("goal_days", 0)
    current = data[user_id].get("current_day", 0)
    amount = data[user_id].get("saved_amount", 0)
    await message.answer(
        f"📊 *Твоя статистика:*\n\n"
        f"Привычка: {habit}\n"
        f"Цель: {goal}\n"
        f"Прогресс: {current}/{days} дней\n"
        f"Накоплено: {amount}₽",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🎯 Изменить цель")
async def change_goal(message: types.Message):
    awaiting_action[message.from_user.id] = "goal"
    await message.answer("Введи новую цель:")

@dp.message(F.text == "💰 Изменить сумму")
async def change_amount(message: types.Message):
    awaiting_action[message.from_user.id] = "amount"
    await message.answer("Введи новую сумму (руб/день):")

@dp.message(F.text == "⏰ Изменить время")
async def change_time(message: types.Message):
    awaiting_action[message.from_user.id] = "time"
    await message.answer("Введи новый час напоминания (0-23):")

@dp.message(F.text == "📅 Изменить дни")
async def change_days(message: types.Message):
    awaiting_action[message.from_user.id] = "days"
    await message.answer("Введи новое количество дней:")

@dp.message(F.text == "⚙️ Сбросить цель")
async def reset_goal(message: types.Message):
    user_id = str(message.from_user.id)
    data[user_id] = {
        "habit": None,
        "daily_amount": 0,
        "goal": None,
        "goal_days": 0,
        "current_day": 0,
        "saved_amount": 0,
        "reminder_hour": DAILY_HOUR
    }
    save_data(data)
    await message.answer("Все данные сброшены. Хочешь настроить новую привычку? Напиши /start.", reply_markup=settings_keyboard)

@dp.message(F.text == "↩️ Ничего не менять")
async def cancel_edit(message: types.Message):
    user_id = message.from_user.id
    awaiting_action.pop(user_id, None)
    pending_changes.pop(user_id, None)
    await message.answer("Изменения отменены. Возвращаюсь в меню настроек.", reply_markup=settings_keyboard)

@dp.message(F.text.in_(["Да", "Нет"]))
async def handle_yes_no(message: types.Message):
    user_id = message.from_user.id
    if user_id in pending_changes:
        if message.text == "Да":
            field, value = pending_changes.pop(user_id)
            data[str(user_id)][field] = value
            save_data(data)
            awaiting_action.pop(user_id, None)
            await message.answer("Супер! Изменения приняты.", reply_markup=settings_keyboard)
        else:
            pending_changes.pop(user_id)
            awaiting_action.pop(user_id, None)
            await message.answer("Изменения отменены.", reply_markup=settings_keyboard)
    else:
        if user_id not in data or data[str(user_id)]["habit"] is None:
            await message.answer("Сначала введи свои данные через /start")
            return
        if message.text == "Да":
            data[str(user_id)]["current_day"] += 1
            data[str(user_id)]["saved_amount"] += data[str(user_id)]["daily_amount"]
            save_data(data)
            await message.answer(f"Ты красавчик! 💪 Ты ближе к цели: {data[str(user_id)]['goal']}, "
                                 f"{data[str(user_id)]['current_day']}/{data[str(user_id)]['goal_days']} дней, "
                                 f"накопил {data[str(user_id)]['saved_amount']}₽.")
        else:
            await message.answer(f"Очень жаль 😿 Завтра новый шанс! "
                                 f"{data[str(user_id)]['current_day']}/{data[str(user_id)]['goal_days']} дней, "
                                 f"в копилке {data[str(user_id)]['saved_amount']}₽.")

@dp.message(F.text)
async def process_input(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in data:
        await message.answer("Сначала введи данные через /start")
        return

    action = awaiting_action.get(message.from_user.id)
    if action:
        try:
            if action == "goal":
                pending_changes[message.from_user.id] = ("goal", message.text)
                await message.answer(f"Ты подтверждаешь изменения цели на: {message.text}?", reply_markup=yes_no_keyboard)
            elif action == "amount":
                amount = int(message.text)
                pending_changes[message.from_user.id] = ("daily_amount", amount)
                await message.answer(f"Ты подтверждаешь изменения суммы на: {amount}₽?", reply_markup=yes_no_keyboard)
            elif action == "time":
                new_hour = int(message.text)
                if 0 <= new_hour <= 23:
                    pending_changes[message.from_user.id] = ("reminder_hour", new_hour)
                    await message.answer(f"Ты подтверждаешь изменения времени на: {new_hour}:00?", reply_markup=yes_no_keyboard)
                else:
                    await message.answer("Час должен быть от 0 до 23.")
            elif action == "days":
                days = int(message.text)
                pending_changes[message.from_user.id] = ("goal_days", days)
                await message.answer(f"Ты подтверждаешь изменения дней на: {days}?", reply_markup=yes_no_keyboard)
        except ValueError:
            await message.answer("Введите число.")

async def send_daily_reminder():
    for user_id in data.keys():
        try:
            hour = data[user_id].get("reminder_hour", DAILY_HOUR)
            if datetime.now().hour == hour:
                await bot.send_message(user_id, f"Ты сегодня победил привычку — {data[user_id]['habit']}?", reply_markup=yes_no_keyboard)
        except Exception as e:
            logging.warning(f"Не смог отправить сообщение пользователю {user_id}: {e}")

async def main():
    scheduler.add_job(send_daily_reminder, "cron", minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
