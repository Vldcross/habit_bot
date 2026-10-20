import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const required = ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "BOT_TOKEN"];
const missing = required.filter(key => !process.env[key]);
if (missing.length) {
  console.error("Задайте в защищённых настройках окружения: " + missing.join(", ") + ". Значения в чат не отправляйте.");
  process.exit(1);
}
const account = process.env.CLOUDFLARE_ACCOUNT_ID;
if (!/^[a-f0-9]{32}$/i.test(account)) {
  console.error("CLOUDFLARE_ACCOUNT_ID должен содержать 32 шестнадцатеричных символа.");
  process.exit(1);
}

async function api(path, method = "GET", body) {
  const response = await fetch(`https://api.cloudflare.com/client/v4/accounts/${account}/${path}`, {
    method, headers: { Authorization: `Bearer ${process.env.CLOUDFLARE_API_TOKEN}`, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(30_000),
  });
  const payload = await response.json();
  if (!response.ok || !payload.success) throw Error(`Cloudflare API: HTTP ${response.status}. Проверьте права токена Workers Scripts Edit и D1 Edit.`);
  return payload.result;
}

async function telegram(method, body = {}) {
  const response = await fetch(`https://api.telegram.org/bot${process.env.BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    signal: AbortSignal.timeout(20_000),
  });
  const payload = await response.json();
  if (!payload.ok) throw Error(`Telegram ${method}: HTTP ${response.status}. Проверьте BOT_TOKEN.`);
  return payload.result;
}

function wrangler(args, input) {
  const bin = resolve(root, "node_modules/wrangler/bin/wrangler.js");
  execFileSync(process.execPath, [bin, ...args], {
    cwd: root, env: { ...process.env, CI: "true", WRANGLER_SEND_METRICS: "false" },
    input, stdio: ["pipe", "inherit", "inherit"],
  });
}

async function deploy() {
  // Validate local code and the existing credential before provisioning anything.
  execFileSync(process.execPath, ["--test", "cloudflare/tests/worker.test.mjs"], { cwd: root, stdio: "inherit" });
  await telegram("getMe");
  const subdomain = await api("workers/subdomain");
  if (!subdomain?.subdomain) throw Error("Сначала откройте Workers & Pages в бесплатном аккаунте Cloudflare и выберите поддомен workers.dev.");
  const base = JSON.parse(readFileSync(resolve(root, "wrangler.json"), "utf8"));
  const databaseName = base.d1_databases[0].database_name;
  const databases = await api("d1/database?per_page=100");
  let database = databases.find(db => db.name === databaseName);
  if (!database) database = await api("d1/database", "POST", { name: databaseName });
  const databaseId = database.uuid || database.id;
  if (!databaseId) throw Error("Cloudflare не вернул идентификатор D1.");
  const config = { ...base, account_id: account, main: resolve(root, base.main),
    d1_databases: [{ ...base.d1_databases[0], database_id: databaseId,
      migrations_dir: resolve(root, "cloudflare/migrations") }] };
  mkdirSync(resolve(root, ".local"), { recursive: true });
  const configFile = resolve(root, ".local/wrangler.deploy.json");
  writeFileSync(configFile, JSON.stringify(config, null, 2) + "\n");
  // The small idempotent schema can use D1's query API directly. Bulk imports
  // require a separately hosted signed upload URL, which restricted networks
  // may block even when api.cloudflare.com is allowed.
  const schema = readFileSync(resolve(root, "cloudflare/migrations/0001_init.sql"), "utf8");
  for (const sql of schema.split(";").map(value => value.trim()).filter(Boolean)) {
    const results = await api(`d1/database/${databaseId}/query`, "POST", { sql });
    if (results.some(result => result.success === false)) throw Error("Cloudflare не применил схему D1.");
  }
  wrangler(["deploy", "--config", configFile]);
  const secret = randomBytes(32).toString("hex");
  // Only stdout contains deployment status. Secret values use stdin, never argv,
  // configuration files, logs or the Git repository.
  wrangler(["secret", "bulk", "--config", configFile], JSON.stringify({ BOT_TOKEN: process.env.BOT_TOKEN, WEBHOOK_SECRET: secret }));
  const address = `https://${config.name}.${subdomain.subdomain}.workers.dev`;
  let healthy = false;
  for (let attempt = 0; attempt < 10; attempt++) {
    try {
      const response = await fetch(address + "/health", { signal: AbortSignal.timeout(10_000) });
      if (response.ok && (await response.json()).ok) { healthy = true; break; }
    } catch { /* Wait for propagation; never print request credentials. */ }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if (!healthy) throw Error("Worker ещё не прошёл проверку /health. Webhook Telegram не изменён; повторите запуск после проверки Cloudflare.");
  await telegram("setWebhook", { url: address + "/telegram", secret_token: secret,
    allowed_updates: ["message"], max_connections: 1, drop_pending_updates: false });
  const webhook = await telegram("getWebhookInfo");
  if (webhook.url !== address + "/telegram") throw Error("Telegram не подтвердил новый webhook.");
  console.log("Готово: " + address + ". Webhook подключён, очередь сохранена. Проверьте бота командой /start.");
}

deploy().catch(error => {
  // Network exceptions can include the token-bearing Telegram URL.
  const safe = error.message?.startsWith("Cloudflare API:") || error.message?.startsWith("Telegram ") ||
    error.message?.startsWith("Сначала ") || error.message?.startsWith("Worker ") ||
    error.message?.startsWith("Cloudflare не ") || error.message?.startsWith("Telegram не ");
  console.error(safe ? error.message : "Развёртывание не завершено. Проверьте сеть, права аккаунта и вывод Wrangler выше.");
  process.exitCode = 1;
});
