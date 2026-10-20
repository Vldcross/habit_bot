import { test } from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import worker, { moscowTime, processUpdate, remind } from "../worker.mjs";

class D1 {
  constructor() {
    this.sql = new DatabaseSync(":memory:");
    this.sql.exec(readFileSync(new URL("../migrations/0001_init.sql", import.meta.url), "utf8"));
  }
  prepare(sql) {
    const statement = this.sql.prepare(sql);
    let params = [];
    return {
      bind(...values) { params = values; return this; },
      async first() { return statement.get(...params) || null; },
      async all() { return { results: statement.all(...params) }; },
      async run() { return { success: true, meta: statement.run(...params) }; },
    };
  }
  async batch(statements) {
    this.sql.exec("BEGIN");
    try {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      this.sql.exec("COMMIT");
      return results;
    } catch (error) { this.sql.exec("ROLLBACK"); throw error; }
  }
}

function fixture(t) {
  const DB = new D1();
  t.after(() => DB.sql.close());
  const env = { DB, BOT_TOKEN: "123:offline-only", WEBHOOK_SECRET: "test-secret" };
  const now = Date.parse("2026-10-20T18:00:00Z");
  let sequence = 0;
  const update = (text, id = ++sequence, user = 123) => ({ update_id: id,
    message: { chat: { id: user, type: "private" }, from: { id: user }, text } });
  const send = (text, id, user, timestamp = now) => processUpdate(update(text, id, user), env, timestamp);
  const goal = (user = 123) => DB.sql.prepare("SELECT * FROM users WHERE user_id=?").get(String(user));
  const request = body => new Request("https://example.test/telegram", { method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": env.WEBHOOK_SECRET }, body: JSON.stringify(body) });
  return { DB, env, now, update, send, goal, request };
}

test("webhook rejects untrusted traffic before touching the database", async t => {
  const f = fixture(t);
  const response = await worker.fetch(new Request("https://example.test/telegram", { method: "POST", body: "{}" }), f.env, {});
  assert.equal(response.status, 403);
  assert.equal(f.DB.sql.prepare("SELECT count(*) AS n FROM users").get().n, 0);
});

test("health checks binding and secrets without exposing them", async t => {
  const f = fixture(t);
  const response = await worker.fetch(new Request("https://example.test/health"), f.env, {});
  assert.deepEqual(await response.json(), { ok: true });
  const missing = await worker.fetch(new Request("https://example.test/health"), { DB: f.DB }, {});
  assert.equal(missing.status, 503);
});

test("malformed JSON is rejected and unknown routes are not public handlers", async t => {
  const f = fixture(t);
  const invalid = new Request("https://example.test/telegram", { method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": f.env.WEBHOOK_SECRET }, body: "{" });
  assert.equal((await worker.fetch(invalid, f.env, {})).status, 400);
  assert.equal((await worker.fetch(new Request("https://example.test/"), f.env, {})).status, 404);
  assert.equal((await worker.fetch(f.request(null), f.env, {})).status, 400);
});

test("private messages only; unsupported updates are acknowledged", async t => {
  const f = fixture(t);
  const update = f.update("/start");
  update.message.chat.type = "group";
  assert.equal(await processUpdate(update, f.env), null);
  assert.equal(await processUpdate({ update_id: 2, callback_query: {} }, f.env), null);
  assert.equal(f.goal(), undefined);
});

test("start creates goal and repeated start preserves savings", async t => {
  const f = fixture(t);
  await f.send("/start"); await f.send("Да"); await f.send("/start");
  assert.equal(f.goal().saved, 100);
  assert.equal(f.goal().days_done, 1);
});

test("settings validate name, amount and days then persist", async t => {
  const f = fixture(t);
  await f.send("⚙️ Настройки");
  assert.match((await f.send("")).reply.text, /название/);
  await f.send("Не курить");
  for (const input of ["0", "-1", "1.5", "1000001", "abc"]) assert.match((await f.send(input)).reply.text, /целая сумма/);
  await f.send("250");
  for (const input of ["0", "-1", "3651", "abc"]) assert.match((await f.send(input)).reply.text, /целое число/);
  await f.send("40");
  const goal = f.goal();
  assert.equal(goal.name, "Не курить"); assert.equal(goal.amount, 250); assert.equal(goal.total_days, 40);
  assert.equal(goal.step, null); assert.equal(goal.active, 1);
});

test("settings steps survive independent invocations; replay cannot skip a step", async t => {
  const f = fixture(t);
  await f.send("/settings", 1); await f.send("Привычка", 2); await f.send("100", 3);
  const replay = await f.send("100", 3);
  assert.match(replay.reply.text, /успешных дней/);
  assert.equal(f.goal().step, "days");
  await f.send("30", 4);
  assert.equal(f.goal().amount, 100); assert.equal(f.goal().total_days, 30);
});

test("cancel discards partial settings and help does not destroy them", async t => {
  const f = fixture(t);
  await f.send("/start"); await f.send("/settings"); await f.send("Изменённая");
  await f.send("/help"); assert.equal(f.goal().step, "amount");
  await f.send("/cancel"); assert.equal(f.goal().name, "Вредная привычка");
  assert.equal(f.goal().step, null);
});

test("yes only credits once per Moscow date, including after a restart", async t => {
  const f = fixture(t);
  await f.send("/start", 1); await f.send("Да", 2); await f.send("Да", 3);
  assert.equal(f.goal().saved, 100);
  assert.match((await f.send("Да", 4)).reply.text, /уже учтён/);
  await f.send("Да", 5, 123, f.now + 86400_000);
  assert.equal(f.goal().saved, 200);
});

test("simultaneous redelivery of one update is idempotent", async t => {
  const f = fixture(t);
  await f.send("/start", 1);
  // D1 executes batches atomically; serialize the shim's transaction boundary.
  const original = f.DB.batch.bind(f.DB);
  let pending = Promise.resolve();
  f.DB.batch = statements => { const next = pending.then(() => original(statements)); pending = next.catch(() => {}); return next; };
  await Promise.all([f.send("Да", 2), f.send("Да", 2)]);
  assert.equal(f.goal().saved, 100);
});

test("no does not prevent later credit; settings preserve savings and credit date", async t => {
  const f = fixture(t);
  await f.send("/start"); await f.send("Нет"); assert.equal(f.goal().saved, 0);
  await f.send("Да");
  for (const text of ["/settings", "Новая", "300", "5"]) await f.send(text);
  await f.send("Да");
  assert.equal(f.goal().saved, 100); assert.equal(f.goal().amount, 300);
});

test("goal completion stops crediting; shorter target cannot erase progress", async t => {
  const f = fixture(t);
  for (const text of ["/settings", "Цель", "50", "1", "Да"]) await f.send(text);
  assert.equal(f.goal().saved, 50);
  await f.send("Да", undefined, 123, f.now + 86400_000);
  assert.equal(f.goal().saved, 50);
  f.DB.sql.prepare("UPDATE users SET days_done=3 WHERE user_id='123'").run();
  for (const text of ["/settings", "Другая", "10"]) await f.send(text);
  assert.match((await f.send("2")).reply.text, /Уже отмечено 3/);
});

test("reset erases only own goal and replay cannot reset a new goal", async t => {
  const f = fixture(t);
  await f.send("/start", 1); await f.send("/start", 2, 456);
  await f.send("/reset_all", 3); await f.send("/start", 4); await f.send("Да", 5);
  await f.send("/reset_all", 3);
  assert.equal(f.goal().saved, 100); assert.equal(f.goal(456).active, 1);
  await f.send("/reset_all", 6);
  assert.equal(f.goal().active, 0); assert.equal(f.goal().name, "");
});

test("statistics and unknown/non-text messages give useful replies", async t => {
  const f = fixture(t);
  assert.match((await f.send(undefined)).reply.text, /\/start/);
  await f.send("/start"); await f.send("Да");
  const statistics = (await f.send("📊 Моя статистика")).reply.text;
  assert.match(statistics, /1\/30/); assert.match(statistics, /100 руб\./);
  assert.match((await f.send(undefined)).reply.text, /\/help/);
});

test("a failed transaction does not credit or cache an update", async t => {
  const f = fixture(t);
  await f.send("/start", 1);
  const batch = f.DB.batch.bind(f.DB);
  f.DB.batch = statements => batch([statements[0], { async run() { throw Error("disk failure"); } }]);
  await assert.rejects(f.send("Да", 2), /disk failure/);
  assert.equal(f.goal().saved, 0);
  assert.equal(f.DB.sql.prepare("SELECT * FROM responses WHERE update_id=2").get(), undefined);
  f.DB.batch = batch;
  await f.send("Да", 2); assert.equal(f.goal().saved, 100);
});

test("database failures request Telegram redelivery without leaking a token", async t => {
  const f = fixture(t);
  f.env.DB = { prepare() { throw new Error(f.env.BOT_TOKEN); } };
  const response = await worker.fetch(f.request(f.update("/start")), f.env, {});
  assert.equal(response.status, 503);
  assert.equal((await response.text()).includes(f.env.BOT_TOKEN), false);
});

test("webhook responds using Telegram API JSON without outbound messages", async t => {
  const f = fixture(t);
  const response = await worker.fetch(f.request(f.update("/start")), f.env, {});
  const payload = await response.json();
  assert.equal(payload.method, "sendMessage"); assert.equal(payload.chat_id, 123);
  assert.ok(payload.reply_markup.resize_keyboard);
});

test("a failed optional photo does not fail the webhook or undo credit", async t => {
  const f = fixture(t);
  await f.send("/start", 1);
  const originalFetch = globalThis.fetch;
  const pending = [];
  globalThis.fetch = async () => { throw Error("unavailable"); };
  try {
    const response = await worker.fetch(f.request(f.update("Да", 2)), f.env,
      { waitUntil(promise) { pending.push(promise); } });
    await Promise.all(pending);
    assert.equal(response.status, 200);
    assert.equal(f.goal().saved, 100);
    assert.equal(pending.length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test("health fails when the database has not been migrated", async t => {
  const f = fixture(t);
  f.DB.sql.exec("DROP TABLE users");
  const response = await worker.fetch(new Request("https://example.test/health"), f.env, {});
  assert.equal(response.status, 503);
});

test("Moscow date changes at 21:00 UTC, reminder hour starts at 18:00 UTC", () => {
  assert.deepEqual(moscowTime(Date.parse("2026-10-20T21:00:00Z")), { date: "2026-10-21", hour: 0 });
  assert.deepEqual(moscowTime(Date.parse("2026-10-20T18:00:00Z")), { date: "2026-10-20", hour: 21 });
});

test("reminders only send to unfinished, not-yet-recorded users once per day", async t => {
  const f = fixture(t);
  for (const user of [1, 2, 3]) await f.send("/start", undefined, user);
  await f.send("Да", undefined, 1);
  f.DB.sql.prepare("UPDATE users SET days_done=total_days WHERE user_id='2'").run();
  const sent = [];
  const fetcher = async (url, options) => { sent.push(JSON.parse(options.body).chat_id); return Response.json({ ok: true }); };
  assert.equal(await remind(f.env, f.now, fetcher), 1);
  assert.deepEqual(sent, ["3"]);
  assert.equal(await remind(f.env, f.now + 60_000, fetcher), 0);
  assert.equal(await remind(f.env, f.now - 3600_000, fetcher), 0);
});

test("transient reminder errors are retried; blocked chats are excluded", async t => {
  const f = fixture(t);
  await f.send("/start", 1, 1); await f.send("/start", 2, 2);
  const fetcher = async (url, options) => Response.json({ ok: false,
    error_code: JSON.parse(options.body).chat_id === "1" ? 403 : 429 });
  assert.equal(await remind(f.env, f.now, fetcher), 0);
  assert.equal(f.goal(1).blocked, 1); assert.equal(f.goal(2).last_reminder_date, null);
  const retried = [];
  await remind(f.env, f.now + 60_000, async (url, options) => { retried.push(JSON.parse(options.body).chat_id); return Response.json({ ok: true }); });
  assert.deepEqual(retried, ["2"]);
});

test("reminder batches stay bounded and continue on the next cron invocation", async t => {
  const f = fixture(t);
  for (let user = 1; user <= 25; user++) await f.send("/start", user, user);
  const fetcher = async () => Response.json({ ok: true });
  assert.equal(await remind(f.env, f.now, fetcher), 20);
  assert.equal(await remind(f.env, f.now + 60_000, fetcher), 5);
});
