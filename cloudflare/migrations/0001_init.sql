CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL DEFAULT '',
    amount INTEGER NOT NULL DEFAULT 0,
    days_done INTEGER NOT NULL DEFAULT 0,
    total_days INTEGER NOT NULL DEFAULT 30,
    saved INTEGER NOT NULL DEFAULT 0,
    last_completed_date TEXT,
    step TEXT,
    draft_name TEXT,
    draft_amount INTEGER,
    last_update_id INTEGER NOT NULL,
    last_reminder_date TEXT,
    blocked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS reminder_candidates ON users(active, blocked);
CREATE TABLE IF NOT EXISTS responses (
    update_id INTEGER PRIMARY KEY,
    reply TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS responses_age ON responses(created_at);
