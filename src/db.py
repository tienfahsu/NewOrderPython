"""D1 (Cloudflare SQLite) 資料庫存取小幫手。"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              TEXT    NOT NULL,
  email             TEXT    NOT NULL UNIQUE,
  password_hash     TEXT    NOT NULL,
  role              TEXT    NOT NULL DEFAULT 'member',
  line_id           TEXT    DEFAULT '',           -- LINE ID 名稱（使用者代碼，供辨識）
  line_user_id      TEXT    DEFAULT '',           -- LINE Messaging API User ID（供推播）
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
  options    TEXT    DEFAULT '[]',            -- JSON: 選項定義 (select/multi/text)
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
"""


# 既有資料庫的欄位新增（idempotent，失敗代表欄位已存在）
SCHEMA_MIGRATIONS = [
    "ALTER TABLE products ADD COLUMN options TEXT DEFAULT '[]'",
    "ALTER TABLE order_items ADD COLUMN options TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN line_user_id TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN line_id TEXT DEFAULT ''",
]


def _strip_sql_comments(sql):
    """移除 SQL 中的 -- 行尾註解（D1 的 exec 不支援註解）。"""
    lines = []
    for line in sql.splitlines():
        if "--" in line:
            line = line.split("--", 1)[0].rstrip()
        lines.append(line)
    return "\n".join(lines)


def _split_sql_statements(sql):
    """把多語句 SQL 依分號拆開，回傳非空、去除前後空白的語句串列。"""
    out = []
    for part in sql.split(";"):
        part = part.strip()
        if part:
            out.append(part)
    return out


class DB:
    """包裝 D1 binding，提供方便的 async 查詢介面。"""

    def __init__(self, binding):
        self._b = binding

    def _stmt(self, sql, params):
        stmt = self._b.prepare(sql)
        if params:
            stmt = stmt.bind(*params)
        return stmt

    async def init_schema(self):
        # D1 的 exec() 對批次/註解解析不穩定，改用 prepare().run() 逐句執行。
        for stmt in _split_sql_statements(_strip_sql_comments(SCHEMA_SQL)):
            await self.run(stmt)
        for sql in SCHEMA_MIGRATIONS:
            try:
                await self.run(sql)
            except Exception:
                pass

    async def run(self, sql, *params):
        res = await self._stmt(sql, params).run()
        return res

    async def last_id(self, sql, *params):
        res = await self._stmt(sql, params).run()
        try:
            meta = self._get(res, "meta")
            return self._get(meta, "last_row_id")
        except Exception:
            return None

    async def all(self, sql, *params):
        res = await self._stmt(sql, params).all()
        rows = self._get(res, "results")
        return rows if rows is not None else []

    async def first(self, sql, *params):
        rows = await self.all(sql, *params)
        return rows[0] if rows else None

    @staticmethod
    def _get(obj, key):
        """同時支援 dict 與 JsProxy 兩種結果物件。"""
        if hasattr(obj, "get"):
            return obj.get(key)
        return getattr(obj, key, None)
