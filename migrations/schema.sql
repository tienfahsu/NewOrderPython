-- Cloudflare D1 資料庫結構
-- 匯入方式：npx wrangler d1 execute team-order-db --remote --file=migrations/schema.sql

CREATE TABLE IF NOT EXISTS users (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              TEXT    NOT NULL,
  email             TEXT    NOT NULL UNIQUE,
  password_hash     TEXT    NOT NULL,
  role              TEXT    NOT NULL DEFAULT 'member',   -- admin | member
  line_user_id      TEXT    DEFAULT '',                  -- LINE Messaging API User ID
  phone             TEXT    DEFAULT '',
  created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vendors (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT    NOT NULL,
  phone      TEXT    DEFAULT '',
  address    TEXT    DEFAULT '',
  note       TEXT    DEFAULT '',
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_id  INTEGER NOT NULL REFERENCES vendors(id),
  name       TEXT    NOT NULL,
  price      INTEGER NOT NULL DEFAULT 0,          -- 單位：新台幣元
  note       TEXT    DEFAULT '',
  options    TEXT    DEFAULT '[]',                -- JSON: 選項定義 (select/multi/text)
  active     INTEGER NOT NULL DEFAULT 1,
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS group_orders (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  title      TEXT    NOT NULL,
  vendor_id  INTEGER REFERENCES vendors(id),
  order_date TEXT    DEFAULT '',                  -- 取餐/送達日期
  deadline   TEXT    DEFAULT '',                  -- 截止訂購時間 (ISO)
  status     TEXT    NOT NULL DEFAULT 'open',     -- open | closed
  note       TEXT    DEFAULT '',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_vendors (
  order_id  INTEGER NOT NULL REFERENCES group_orders(id),
  vendor_id INTEGER NOT NULL REFERENCES vendors(id),
  PRIMARY KEY (order_id, vendor_id)
);

CREATE TABLE IF NOT EXISTS share_tokens (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  token      TEXT    NOT NULL UNIQUE,
  order_id   INTEGER NOT NULL REFERENCES group_orders(id),
  created_by INTEGER NOT NULL REFERENCES users(id),
  expires_at TEXT    NOT NULL,
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id   INTEGER NOT NULL REFERENCES group_orders(id),
  user_id    INTEGER NOT NULL REFERENCES users(id),
  product_id INTEGER NOT NULL REFERENCES products(id),
  quantity   INTEGER NOT NULL DEFAULT 1,
  unit_price INTEGER NOT NULL DEFAULT 0,          -- 下訂當時的價格快照
  options    TEXT    DEFAULT '',                  -- JSON: 已選客製化選項
  created_at TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (order_id, user_id, product_id)
);

CREATE TABLE IF NOT EXISTS payments (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id               INTEGER NOT NULL REFERENCES group_orders(id),
  user_id                INTEGER NOT NULL REFERENCES users(id),
  amount                 INTEGER NOT NULL DEFAULT 0,
  status                 TEXT    NOT NULL DEFAULT 'unpaid',  -- unpaid | pending | paid
  method                 TEXT    DEFAULT '',                 -- cash | transfer | linepay | other
  linepay_transaction_id TEXT    DEFAULT '',
  linepay_access_token   TEXT    DEFAULT '',
  paid_at                TEXT,
  updated_at             TEXT,
  UNIQUE (order_id, user_id)
);

CREATE TABLE IF NOT EXISTS notifications (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id),
  title      TEXT    DEFAULT '',
  message    TEXT    NOT NULL,
  read       INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminder_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id   INTEGER NOT NULL,
  user_id    INTEGER NOT NULL,
  channel    TEXT    NOT NULL,    -- app | line | email
  status     TEXT    NOT NULL,    -- sent | failed | skipped
  detail     TEXT    DEFAULT '',
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
