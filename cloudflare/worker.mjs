const keyboard = {
  keyboard: [[{ text: "📊 Моя статистика" }], [{ text: "Да" }, { text: "Нет" }], [{ text: "⚙️ Настройки" }]],
  resize_keyboard: true,
};
const clock = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", hourCycle: "h23",
});
const cacheAge = 2 * 86400_000;

export function moscowTime(now = Date.now()) {
  const parts = Object.fromEntries(clock.formatToParts(new Date(now)).map(p => [p.type, p.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) };
}

function progress(goal) {
  return `Цель: ${goal.name}\nСумма за день: ${goal.amount} руб.\nДней достигнуто: ${goal.days_done}/${goal.total_days}\nНакоплено: ${goal.saved} руб.`;
}

function positive(text, maximum) {
  if (!/^[0-9]{1,10}$/.test(text)) return null;
  const result = Number(text);
  return result >= 1 && result <= maximum ? result : null;
}

function defaultGoal(user) {
  return { ...user, active: 1, name: "Вредная привычка", amount: 100, days_done: 0,
    total_days: 30, saved: 0, last_completed_date: null, step: null,
    draft_name: null, draft_amount: null };
}

export function handleMessage(existing, message, date) {
  let user = { ...(existing || { user_id: String(message.from.id), active: 0,
    name: "", amount: 0, days_done: 0, total_days: 30, saved: 0,
    last_completed_date: null, step: null, draft_name: null, draft_amount: null }),
    chat_id: String(message.chat.id) };
  const text = (message.text || "").trim();
  const command = text.split(/\s/)[0].split("@")[0];
  let answer;
  let cat = false;
  if (command === "/start") {
    if (!user.active) user = defaultGoal(user);
    user.step = user.draft_name = user.draft_amount = null;
    answer = "Привет! Я помогу побеждать привычку и копить на цель.\n" +
      "Открой ⚙️ Настройки: название, сумма и число дней. «Да» учитывается один раз за день по Москве.\n" +
      "Напоминания — с 21:00 по Москве.\n/settings — настройки\n/help — помощь\n" +
      "/cancel — отмена настройки\n/reset_all — удалить свою цель.\nПовторный /start сохраняет прогресс.";
  } else if (command === "/help") {
    answer = "/start — начать\n/settings — привычка, сумма, дни\n/cancel — отмена настройки\n" +
      "/reset_all — удалить свою цель\n«Да» — успешный день, «Нет» — оставить прогресс без изменений.\n" +
      "«📊 Моя статистика» — накопления. Напоминания — с 21:00 по Москве.";
  } else if (command === "/cancel") {
    user.step = user.draft_name = user.draft_amount = null;
    answer = "Настройка отменена. Прогресс сохранён.";
  } else if (command === "/reset_all") {
    user = { ...user, active: 0, name: "", amount: 0, days_done: 0, total_days: 30,
      saved: 0, last_completed_date: null, step: null, draft_name: null, draft_amount: null };
    answer = "Твоя цель удалена. Нажми /start, чтобы начать заново.";
  } else if (command === "/settings" || text === "⚙️ Настройки") {
    user.step = "name";
    user.draft_name = user.draft_amount = null;
    answer = "Какую привычку хочешь победить? Введи название до 100 символов.\n/cancel — отмена.";
  } else if (user.step === "name") {
    if (!text || text.length > 100 || text.startsWith("/")) {
      answer = "Введи название от 1 до 100 символов или /cancel.";
    } else {
      user.draft_name = text;
      user.step = "amount";
      answer = "Сколько рублей откладывать за день? Целое число от 1 до 1 000 000.";
    }
  } else if (user.step === "amount") {
    const amount = positive(text, 1_000_000);
    if (amount === null) answer = "Нужна целая сумма от 1 до 1 000 000 рублей.";
    else {
      user.draft_amount = amount;
      user.step = "days";
      answer = "Сколько успешных дней нужно? Целое число от 1 до 3650.";
    }
  } else if (user.step === "days") {
    const days = positive(text, 3650);
    if (days === null) answer = "Нужно целое число от 1 до 3650.";
    else if (days < user.days_done) answer = `Уже отмечено ${user.days_done} дней. Выбери не меньше этого числа.`;
    else {
      Object.assign(user, { active: 1, name: user.draft_name, amount: user.draft_amount,
        total_days: days, step: null, draft_name: null, draft_amount: null });
      answer = "Настройки сохранены.\n" + progress(user);
    }
  } else if (!user.active) answer = "Нажми /start, чтобы задать цель.";
  else if (text === "Да") {
    if (user.days_done >= user.total_days) answer = "Цель уже достигнута! Для новой цели используй /reset_all и /start.";
    else if (user.last_completed_date === date) answer = "Сегодняшний день уже учтён. Приходи завтра!";
    else {
      user.days_done += 1;
      user.saved += user.amount;
      user.last_completed_date = date;
      answer = "Отлично! Прогресс обновлён. 🐱\n" + progress(user);
      if (user.days_done === user.total_days) answer += "\n🎉 Поздравляю, цель достигнута!";
      cat = true;
    }
  } else if (text === "Нет") answer = "Не сдавайся! Завтра будет новый шанс.";
  else if (text === "📊 Моя статистика") answer = progress(user);
  else answer = "Используй кнопки или /help.";
  return { user, cat, reply: { method: "sendMessage", chat_id: message.chat.id, text: answer, reply_markup: keyboard } };
}

const columns = ["user_id", "chat_id", "active", "name", "amount", "days_done", "total_days", "saved",
  "last_completed_date", "step", "draft_name", "draft_amount", "last_update_id"];
const upsert = `INSERT INTO users (${columns.join(",")}) VALUES (${columns.map(() => "?").join(",")})
  ON CONFLICT(user_id) DO UPDATE SET ${columns.slice(1).map(key => `${key}=excluded.${key}`).join(",")},blocked=0
  WHERE users.last_update_id != excluded.last_update_id`;

export async function processUpdate(update, env, now = Date.now()) {
  const message = update.message;
  if (!Number.isSafeInteger(update.update_id) || !message || message.chat?.type !== "private" ||
      !Number.isSafeInteger(message.from?.id) || !Number.isSafeInteger(message.chat?.id) || message.from.is_bot) return null;
  const cached = await env.DB.prepare("SELECT reply FROM responses WHERE update_id=? AND created_at>=?")
    .bind(update.update_id, now - cacheAge).first();
  if (cached) return { reply: JSON.parse(cached.reply), cat: false };
  const existing = await env.DB.prepare("SELECT * FROM users WHERE user_id=?").bind(String(message.from.id)).first();
  if (existing?.last_update_id === update.update_id) return null;
  const result = handleMessage(existing, message, moscowTime(now).date);
  result.user.last_update_id = update.update_id;
  // A retry cannot advance settings or credit a day twice. State and the reply
  // are committed together; a failed D1 batch is retried by Telegram.
  await env.DB.batch([
    env.DB.prepare(upsert).bind(...columns.map(key => result.user[key] ?? null)),
    env.DB.prepare(`INSERT INTO responses (update_id,reply,created_at) VALUES (?,?,?)
      ON CONFLICT(update_id) DO UPDATE SET reply=excluded.reply,created_at=excluded.created_at
      WHERE responses.created_at<?`)
      .bind(update.update_id, JSON.stringify(result.reply), now, now - cacheAge),
  ]);
  return result;
}

async function telegram(env, method, body, fetcher = fetch) {
  try {
    const response = await fetcher(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(body), signal: AbortSignal.timeout(10_000),
    });
    return await response.json();
  } catch {
    // Do not expose URLs, which contain BOT_TOKEN, in logs.
    return { ok: false };
  }
}

export async function remind(env, now = Date.now(), fetcher = fetch) {
  const time = moscowTime(now);
  if (time.hour !== 21) return 0;
  const { results } = await env.DB.prepare(`UPDATE users SET last_reminder_date=? WHERE user_id IN (
    SELECT user_id FROM users WHERE active=1 AND blocked=0 AND days_done<total_days
    AND (last_completed_date IS NULL OR last_completed_date!=?)
    AND (last_reminder_date IS NULL OR last_reminder_date!=?) LIMIT 20
  ) RETURNING user_id,chat_id`).bind(time.date, time.date, time.date).all();
  let delivered = 0;
  const failures = [];
  for (const user of results) {
    const response = await telegram(env, "sendMessage", {
      chat_id: user.chat_id, text: "Ты победил привычку сегодня?", reply_markup: keyboard,
    }, fetcher);
    if (response.ok) delivered++;
    else if (response.error_code === 403) failures.push(env.DB.prepare("UPDATE users SET blocked=1 WHERE user_id=?").bind(user.user_id));
    else failures.push(env.DB.prepare("UPDATE users SET last_reminder_date=NULL WHERE user_id=? AND last_reminder_date=?").bind(user.user_id, time.date));
  }
  if (failures.length) await env.DB.batch(failures);
  // Indexed cleanup bounds storage on the free tier.
  await env.DB.prepare("DELETE FROM responses WHERE created_at<?").bind(now - cacheAge).run();
  return delivered;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      try {
        if (!env.BOT_TOKEN || !env.WEBHOOK_SECRET) return new Response("Not configured", { status: 503 });
        await env.DB.prepare("SELECT user_id FROM users LIMIT 1").first();
        return Response.json({ ok: true });
      } catch { return new Response("Database unavailable", { status: 503 }); }
    }
    if (url.pathname !== "/telegram" || request.method !== "POST") return new Response("Not found", { status: 404 });
    if (!env.WEBHOOK_SECRET || request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }
    if (!env.BOT_TOKEN) return new Response("Not configured", { status: 503 });
    try {
      const body = await request.text();
      if (body.length > 100_000) return new Response("Too large", { status: 413 });
      let update;
      try { update = JSON.parse(body); }
      catch { return new Response("Invalid JSON", { status: 400 }); }
      if (!update || typeof update !== "object") return new Response("Invalid update", { status: 400 });
      const result = await processUpdate(update, env);
      if (!result) return new Response("OK");
      if (result.cat && env.SEND_CAT_PHOTOS !== "false") ctx.waitUntil(telegram(env, "sendPhoto", {
        chat_id: result.reply.chat_id, photo: "https://i.imgur.com/WxJ7d8C.jpeg", caption: "Молодец! 🐱",
      }));
      // Telegram supports API calls directly in its webhook's JSON response.
      return Response.json(result.reply);
    } catch {
      return new Response("Temporary failure", { status: 503 });
    }
  },
  async scheduled(controller, env) {
    if (env.BOT_TOKEN) await remind(env, controller.scheduledTime);
  },
};
