-- 測試用範例資料（自動產生）

CREATE TABLE IF NOT EXISTS users (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              TEXT    NOT NULL,
  email             TEXT    NOT NULL UNIQUE,
  password_hash     TEXT    NOT NULL,
  role              TEXT    NOT NULL DEFAULT 'member',
  line_notify_token TEXT    DEFAULT '',
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

INSERT OR IGNORE INTO users (id, name, email, password_hash, role, created_at) VALUES (1, '系統管理員', 'admin@example.com', 'pbkdf2$100000$k6dhIW/qm11/XQssri/UoA==$7eDlCi7GlNDcuvuzpGIyfYTGALtxfck6Vaih20HauD0=', 'admin', '2026-08-01 08:00:00');
INSERT OR IGNORE INTO users (id, name, email, password_hash, role, created_at) VALUES (2, '陳小明', 'chen@example.com', 'pbkdf2$100000$KnDNYfBfGHQT1UdpCoSelQ==$D4r+P4nyoNg1IY5HkRaYixbK645ebqmbXaVhtjXlWx4=', 'member', '2026-08-01 08:00:00');
INSERT OR IGNORE INTO users (id, name, email, password_hash, role, created_at) VALUES (3, '林小美', 'lin@example.com', 'pbkdf2$100000$H/Ivy1zmOi4xxxH/rYtUVw==$z5N07wRZnxq8ftpkYoKZGU9FdzxH4jaMr83vtS/Puz8=', 'member', '2026-08-01 08:00:00');
INSERT OR IGNORE INTO users (id, name, email, password_hash, role, created_at) VALUES (4, '張大頭', 'zhang@example.com', 'pbkdf2$100000$3YyyPSNoHj3ov09/qScL9A==$Bxl9qQ8kMwlhKS3ZUJvsBr2NT4ck1zw+Hoq2QTLpWMo=', 'member', '2026-08-01 08:00:00');
INSERT INTO vendors (id, name, phone, address, note, created_at) VALUES (1, '大王便當店', '02-2567-8899', '台北市中山區南京東路三段 88 號', '可送達 12:00 前', '2026-08-02 08:00:00');
INSERT INTO vendors (id, name, phone, address, note, created_at) VALUES (2, '茶茶手搖飲', '02-2745-1122', '台北市松山區八德路四段 123 號', '滿 300 免外送費', '2026-08-02 08:00:00');
INSERT INTO vendors (id, name, phone, address, note, created_at) VALUES (3, '小籠包蒸籠', '02-2333-4455', '台北市中正區開封街一段 45 號', '週一至週五供應', '2026-08-02 08:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (1, 1, '招牌雞腿便當', 95, '附三樣配菜', '[{"key": "rice", "label": "飯量", "type": "select", "choices": ["正常", "少飯", "不加飯"]}, {"key": "sides", "label": "配菜", "type": "multi", "choices": ["高麗菜", "滷蛋", "豆干", "青菜"]}, {"key": "note", "label": "備註", "type": "text", "placeholder": "如：不要辣"}]', '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (2, 1, '香酥排骨便當', 90, '附三樣配菜', '[{"key": "rice", "label": "飯量", "type": "select", "choices": ["正常", "少飯", "不加飯"]}, {"key": "sides", "label": "配菜", "type": "multi", "choices": ["高麗菜", "滷蛋", "豆干", "青菜"]}]', '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (3, 1, '蒜泥白肉便當', 100, '附三樣配菜', NULL, '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (4, 1, '素食便當', 85, '需提前告知', NULL, '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (5, 2, '珍珠奶茶', 60, '可選微糖/無糖', '[{"key": "ice", "label": "冰量", "type": "select", "choices": ["正常冰", "少冰", "去冰"]}, {"key": "sugar", "label": "甜度", "type": "select", "choices": ["全糖", "七分糖", "半糖", "微糖", "無糖"]}, {"key": "topping", "label": "加料", "type": "multi", "choices": ["珍珠", "椰果", "仙草", "布丁"], "prices": {"珍珠": 10, "椰果": 5, "仙草": 5, "布丁": 10}}, {"key": "note", "label": "備註", "type": "text", "placeholder": "如：少冰少甜"}]', '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (6, 2, '四季春青茶', 35, '冰/熱皆可', '[{"key": "temp", "label": "冷熱", "type": "select", "choices": ["冰", "去冰", "熱"]}, {"key": "sugar", "label": "甜度", "type": "select", "choices": ["半糖", "微糖", "無糖"]}]', '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (7, 2, '鮮奶茶', 55, '可選微糖/無糖', '[{"key": "ice", "label": "冰量", "type": "select", "choices": ["正常冰", "少冰", "去冰"]}, {"key": "sugar", "label": "甜度", "type": "select", "choices": ["全糖", "半糖", "微糖", "無糖"]}, {"key": "topping", "label": "加料", "type": "multi", "choices": ["珍珠", "椰果", "仙草", "布丁"], "prices": {"珍珠": 10, "椰果": 5, "仙草": 5, "布丁": 10}}, {"key": "note", "label": "備註", "type": "text", "placeholder": "如：不要加糖"}]', '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (8, 2, '檸檬紅茶', 50, '含新鮮檸檬', '[{"key": "ice", "label": "冰量", "type": "select", "choices": ["正常冰", "少冰", "去冰"]}, {"key": "sugar", "label": "甜度", "type": "select", "choices": ["半糖", "微糖", "無糖"]}, {"key": "lemon", "label": "檸檬", "type": "select", "choices": ["正常", "多檸檬", "不要檸檬"], "prices": {"多檸檬": 10}}]', '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (9, 3, '小籠包 (8入)', 120, '附薑絲與醬油', '[{"key": "sauce", "label": "醬油", "type": "select", "choices": ["正常", "少醬油", "不要醬油"]}, {"key": "note", "label": "備註", "type": "text", "placeholder": "如：多帶一份薑絲"}]', '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (10, 3, '鍋貼 (10入)', 80, '附沾醬', NULL, '2026-08-02 09:00:00');
INSERT INTO products (id, vendor_id, name, price, note, options, created_at) VALUES (11, 3, '酸辣湯', 45, '中碗', '[{"key": "spicy", "label": "辣度", "type": "select", "choices": ["不辣", "小辣", "中辣", "大辣"]}, {"key": "note", "label": "備註", "type": "text", "placeholder": "如：多加蔥"}]', '2026-08-02 09:00:00');
INSERT INTO group_orders (id, title, vendor_id, order_date, deadline, status, note, created_by, created_at) VALUES (1, '週五午餐團 - 大王便當', 1, '2026-08-14', '2026-08-14 04:00:00', 'closed', '請於 11:50 在一樓櫃台自取', 1, '2026-08-13 09:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (1, 1, 1, 1, 2, 95, '{"rice": "少飯", "sides": ["滷蛋", "青菜"], "note": "不要辣"}', '2026-08-13 09:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (2, 1, 2, 2, 1, 90, '{"rice": "正常", "sides": ["高麗菜", "豆干"]}', '2026-08-13 09:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (3, 1, 2, 3, 1, 100, '', '2026-08-13 09:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (4, 1, 3, 4, 1, 85, '', '2026-08-13 09:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (5, 1, 4, 1, 1, 95, '{"rice": "少飯", "sides": ["滷蛋"]}', '2026-08-13 09:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (6, 1, 4, 4, 1, 85, '', '2026-08-13 09:00:00');
INSERT INTO payments (id, order_id, user_id, amount, status, method, paid_at, updated_at) VALUES (1, 1, 1, 190, 'paid', 'cash', '2026-08-14 03:00:00', '2026-08-13 09:00:00');
INSERT INTO payments (id, order_id, user_id, amount, status, method, paid_at, updated_at) VALUES (2, 1, 2, 190, 'unpaid', '', NULL, '2026-08-13 09:00:00');
INSERT INTO payments (id, order_id, user_id, amount, status, method, paid_at, updated_at) VALUES (3, 1, 3, 85, 'paid', 'transfer', '2026-08-14 02:30:00', '2026-08-13 09:00:00');
INSERT INTO payments (id, order_id, user_id, amount, status, method, paid_at, updated_at) VALUES (4, 1, 4, 180, 'unpaid', '', NULL, '2026-08-13 09:00:00');
INSERT INTO group_orders (id, title, vendor_id, order_date, deadline, status, note, created_by, created_at) VALUES (2, '週三下午茶 - 茶茶手搖飲', 2, '2026-08-19', '2026-08-19 03:00:00', 'open', '每人限 2 杯', 1, '2026-08-18 01:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (7, 2, 1, 5, 1, 80, '{"ice": "少冰", "sugar": "微糖", "topping": ["珍珠", "布丁"]}', '2026-08-18 01:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (8, 2, 2, 6, 2, 35, '{"temp": "熱", "sugar": "無糖"}', '2026-08-18 01:00:00');
INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) VALUES (9, 2, 3, 7, 1, 60, '{"ice": "去冰", "sugar": "半糖", "topping": ["椰果"], "note": "不要太甜"}', '2026-08-18 01:00:00');
INSERT INTO group_orders (id, title, vendor_id, order_date, deadline, status, note, created_by, created_at) VALUES (3, '下週一早餐團 - 小籠包蒸籠', 3, '2026-08-24', '2026-08-24 02:00:00', 'open', '', 1, '2026-08-18 02:00:00');
INSERT INTO notifications (id, user_id, title, message, read, created_at) VALUES (1, 2, '【催款通知】週五午餐團 - 尚未付款', '陳小明 您好：
您在「週五午餐團 - 大王便當」的訂單尚有 NT$190 未付款，請盡速處理，謝謝！
http://127.0.0.1:8787/#/orders/1', 0, '2026-08-14 04:10:00');
INSERT INTO notifications (id, user_id, title, message, read, created_at) VALUES (2, 4, '【催款通知】週五午餐團 - 尚未付款', '張大頭 您好：
您在「週五午餐團 - 大王便當」的訂單尚有 NT$180 未付款，請盡速處理，謝謝！
http://127.0.0.1:8787/#/orders/1', 0, '2026-08-14 04:10:00');
INSERT INTO reminder_logs (id, order_id, user_id, channel, status, detail, created_at) VALUES (1, 1, 2, 'app', 'sent', 'app', '2026-08-14 04:10:00');
INSERT INTO reminder_logs (id, order_id, user_id, channel, status, detail, created_at) VALUES (2, 1, 2, 'line', 'skipped', '無 LINE 通知權杖', '2026-08-14 04:10:00');
INSERT INTO reminder_logs (id, order_id, user_id, channel, status, detail, created_at) VALUES (3, 1, 2, 'email', 'skipped', '未設定 RESEND_API_KEY', '2026-08-14 04:10:00');
INSERT INTO reminder_logs (id, order_id, user_id, channel, status, detail, created_at) VALUES (4, 1, 4, 'app', 'sent', 'app', '2026-08-14 04:10:00');
INSERT INTO reminder_logs (id, order_id, user_id, channel, status, detail, created_at) VALUES (5, 1, 4, 'line', 'skipped', '無 LINE 通知權杖', '2026-08-14 04:10:00');
INSERT INTO reminder_logs (id, order_id, user_id, channel, status, detail, created_at) VALUES (6, 1, 4, 'email', 'skipped', '未設定 RESEND_API_KEY', '2026-08-14 04:10:00');
