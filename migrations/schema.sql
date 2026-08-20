-- Cloudflare D1 資料庫結構
-- 匯入方式：npx wrangler d1 execute team-order-db --remote --file=migrations/schema.sql

CREATE TABLE IF NOT EXISTS users (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              TEXT    NOT NULL,
  email             TEXT    NOT NULL UNIQUE,
  password_hash     TEXT    NOT NULL,
  role              TEXT    NOT NULL DEFAULT 'member',
  line_id           TEXT    DEFAULT '',
  line_user_id      TEXT    DEFAULT '',
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
  price      INTEGER NOT NULL DEFAULT 0,
  note       TEXT    DEFAULT '',
  options    TEXT    DEFAULT '[]',
  active     INTEGER NOT NULL DEFAULT 1,
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS group_orders (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  title      TEXT    NOT NULL,
  vendor_id  INTEGER REFERENCES vendors(id),
  order_date TEXT    DEFAULT '',
  deadline   TEXT    DEFAULT '',
  status     TEXT    NOT NULL DEFAULT 'open',
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
  unit_price INTEGER NOT NULL DEFAULT 0,
  options    TEXT    DEFAULT '',
  created_at TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (order_id, user_id, product_id)
);

CREATE TABLE IF NOT EXISTS payments (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id               INTEGER NOT NULL REFERENCES group_orders(id),
  user_id                INTEGER NOT NULL REFERENCES users(id),
  amount                 INTEGER NOT NULL DEFAULT 0,
  status                 TEXT    NOT NULL DEFAULT 'unpaid',
  method                 TEXT    DEFAULT '',
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
  channel    TEXT    NOT NULL,
  status     TEXT    NOT NULL,
  detail     TEXT    DEFAULT '',
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);