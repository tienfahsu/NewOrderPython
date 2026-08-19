"""建立測試用的範例資料：廠商、商品、成員帳號、訂單、收款與催款紀錄。

用法：
  .venv\\Scripts\\python.exe scripts\\seed_samples.py
       # 寫入本地 data/team-order.db（請先停止 local_dev.py）

  .venv\\Scripts\\python.exe scripts\\seed_samples.py --sql migrations\\seed_samples.sql
       # 額外產出 SQL 檔，可匯入遠端 D1：
       #   npx wrangler d1 execute team-order-db --remote --file=migrations\\seed_samples.sql
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from db import SCHEMA_SQL  # noqa: E402

import auth  # noqa: E402
import options as optionsmod  # noqa: E402

# ------------------------------------------------------------------ 資料定義

USERS = [
    # (name, email, password, role)
    ("系統管理員", "admin@example.com", "admin12345", "admin"),
    ("陳小明", "chen@example.com", "pass12345", "member"),
    ("林小美", "lin@example.com", "pass12345", "member"),
    ("張大頭", "zhang@example.com", "pass12345", "member"),
]

# 各成員的 LINE ID 名稱（作「使用者代碼」，供 QR/辨識）
USERS_LINE_ID = {
    "chen@example.com": "chen_ming",
    "lin@example.com": "lin_mei",
    "zhang@example.com": "zhang_head",
}

VENDORS = [
    # (name, phone, address, note)
    ("大王便當店", "02-2567-8899", "台北市中山區南京東路三段 88 號", "可送達 12:00 前"),
    ("茶茶手搖飲", "02-2745-1122", "台北市松山區八德路四段 123 號", "滿 300 免外送費"),
    ("小籠包蒸籠", "02-2333-4455", "台北市中正區開封街一段 45 號", "週一至週五供應"),
]

PRODUCTS = [
    # (vendor_id, name, price, note, options)
    (1, "招牌雞腿便當", 95, "附三樣配菜",
     [{"key": "rice", "label": "飯量", "type": "select", "choices": ["正常", "少飯", "不加飯"]},
      {"key": "sides", "label": "配菜", "type": "multi", "choices": ["高麗菜", "滷蛋", "豆干", "青菜"]},
      {"key": "note", "label": "備註", "type": "text", "placeholder": "如：不要辣"}],
    ),
    (1, "香酥排骨便當", 90, "附三樣配菜",
     [{"key": "rice", "label": "飯量", "type": "select", "choices": ["正常", "少飯", "不加飯"]},
      {"key": "sides", "label": "配菜", "type": "multi", "choices": ["高麗菜", "滷蛋", "豆干", "青菜"]}],
    ),
    (1, "蒜泥白肉便當", 100, "附三樣配菜", None),
    (1, "素食便當", 85, "需提前告知", None),
    (2, "珍珠奶茶", 60, "可選微糖/無糖",
     [{"key": "ice", "label": "冰量", "type": "select", "choices": ["正常冰", "少冰", "去冰"]},
      {"key": "sugar", "label": "甜度", "type": "select", "choices": ["全糖", "七分糖", "半糖", "微糖", "無糖"]},
      {"key": "topping", "label": "加料", "type": "multi", "choices": ["珍珠", "椰果", "仙草", "布丁"],
       "prices": {"珍珠": 10, "椰果": 5, "仙草": 5, "布丁": 10}},
      {"key": "note", "label": "備註", "type": "text", "placeholder": "如：少冰少甜"}],
    ),
    (2, "四季春青茶", 35, "冰/熱皆可",
     [{"key": "temp", "label": "冷熱", "type": "select", "choices": ["冰", "去冰", "熱"]},
      {"key": "sugar", "label": "甜度", "type": "select", "choices": ["半糖", "微糖", "無糖"]}],
    ),
    (2, "鮮奶茶", 55, "可選微糖/無糖",
     [{"key": "ice", "label": "冰量", "type": "select", "choices": ["正常冰", "少冰", "去冰"]},
      {"key": "sugar", "label": "甜度", "type": "select", "choices": ["全糖", "半糖", "微糖", "無糖"]},
      {"key": "topping", "label": "加料", "type": "multi", "choices": ["珍珠", "椰果", "仙草", "布丁"],
       "prices": {"珍珠": 10, "椰果": 5, "仙草": 5, "布丁": 10}},
      {"key": "note", "label": "備註", "type": "text", "placeholder": "如：不要加糖"}],
    ),
    (2, "檸檬紅茶", 50, "含新鮮檸檬",
     [{"key": "ice", "label": "冰量", "type": "select", "choices": ["正常冰", "少冰", "去冰"]},
      {"key": "sugar", "label": "甜度", "type": "select", "choices": ["半糖", "微糖", "無糖"]},
      {"key": "lemon", "label": "檸檬", "type": "select", "choices": ["正常", "多檸檬", "不要檸檬"],
       "prices": {"多檸檬": 10}}],
    ),
    (3, "小籠包 (8入)", 120, "附薑絲與醬油",
     [{"key": "sauce", "label": "醬油", "type": "select", "choices": ["正常", "少醬油", "不要醬油"]},
      {"key": "note", "label": "備註", "type": "text", "placeholder": "如：多帶一份薑絲"}],
    ),
    (3, "鍋貼 (10入)", 80, "附沾醬", None),
    (3, "酸辣湯", 45, "中碗",
     [{"key": "spicy", "label": "辣度", "type": "select", "choices": ["不辣", "小辣", "中辣", "大辣"]},
      {"key": "note", "label": "備註", "type": "text", "placeholder": "如：多加蔥"}],
    ),
]

# 訂單資料：status = open | closed
# items: (order_no, user_email, product_no, quantity, options)  # options 為 dict 或 None
# payments: (order_no, user_email, status, method, paid_at)
ORDERS = [
    {
        "no": 1,
        "title": "週五午餐團 - 大王便當",
        "vendor_id": 1,
        "order_date": "2026-08-14",
        "deadline": "2026-08-14 04:00:00",
        "status": "closed",
        "note": "請於 11:50 在一樓櫃台自取",
        "created_at": "2026-08-13 09:00:00",
        "created_by": "admin@example.com",
        "items": [
            # (user_email, product_no, qty, options)
            ("admin@example.com", 1, 2, {"rice": "少飯", "sides": ["滷蛋", "青菜"], "note": "不要辣"}),
            ("chen@example.com", 2, 1, {"rice": "正常", "sides": ["高麗菜", "豆干"]}),
            ("chen@example.com", 3, 1, None),
            ("lin@example.com", 4, 1, None),
            ("zhang@example.com", 1, 1, {"rice": "少飯", "sides": ["滷蛋"]}),
            ("zhang@example.com", 4, 1, None),
        ],
        "payments": [
            ("admin@example.com", "paid", "cash", "2026-08-14 03:00:00"),
            ("chen@example.com", "unpaid", "", None),
            ("lin@example.com", "paid", "transfer", "2026-08-14 02:30:00"),
            ("zhang@example.com", "unpaid", "", None),
        ],
    },
    {
        "no": 2,
        "title": "週三下午茶 - 茶茶手搖飲",
        "vendor_id": 2,
        "order_date": "2026-08-19",
        "deadline": "2026-08-19 03:00:00",
        "status": "open",
        "note": "每人限 2 杯",
        "created_at": "2026-08-18 01:00:00",
        "created_by": "admin@example.com",
        "items": [
            # (user_email, product_no, qty, options)
            ("admin@example.com", 5, 1, {"ice": "少冰", "sugar": "微糖", "topping": ["珍珠", "布丁"]}),
            ("chen@example.com", 6, 2, {"temp": "熱", "sugar": "無糖"}),
            ("lin@example.com", 7, 1, {"ice": "去冰", "sugar": "半糖", "topping": ["椰果"], "note": "不要太甜"}),
        ],
        "payments": [],
    },
    {
        "no": 3,
        "title": "下週一早餐團 - 小籠包蒸籠",
        "vendor_id": 3,
        "order_date": "2026-08-24",
        "deadline": "2026-08-24 02:00:00",
        "status": "open",
        "note": "",
        "created_at": "2026-08-18 02:00:00",
        "created_by": "admin@example.com",
        "items": [],
        "payments": [],
    },
]

NOTIFICATIONS = [
    # (user_email, title, message, read)
    ("chen@example.com", "【催款通知】週五午餐團 - 尚未付款",
     "陳小明 您好：\n您在「週五午餐團 - 大王便當」的訂單尚有 NT$190 未付款，請盡速處理，謝謝！\nhttp://127.0.0.1:8787/#/orders/1", 0),
    ("zhang@example.com", "【催款通知】週五午餐團 - 尚未付款",
     "張大頭 您好：\n您在「週五午餐團 - 大王便當」的訂單尚有 NT$180 未付款，請盡速處理，謝謝！\nhttp://127.0.0.1:8787/#/orders/1", 0),
]

REMINDER_LOGS = [
    # (order_no, user_email, channel, status, detail)
    (1, "chen@example.com", "app", "sent", "app"),
    (1, "chen@example.com", "line", "skipped", "未綁定 LINE"),
    (1, "chen@example.com", "email", "skipped", "未設定 RESEND_API_KEY"),
    (1, "zhang@example.com", "app", "sent", "app"),
    (1, "zhang@example.com", "line", "skipped", "未綁定 LINE"),
    (1, "zhang@example.com", "email", "skipped", "未設定 RESEND_API_KEY"),
]


# ------------------------------------------------------------------ 執行

def build_sql():
    """回傳 [sql_statement, ...]，同時可用於本地執行與產出 SQL 檔。"""
    statements = []
    statements.append(SCHEMA_SQL)

    product_price = {i + 1: p[2] for i, p in enumerate(PRODUCTS)}  # product_no -> price
    product_defs = {i + 1: optionsmod.parse_defs(p[4]) for i, p in enumerate(PRODUCTS)}  # product_no -> defs

    def unit_price(pno, opts):
        return product_price[pno] + optionsmod.compute_surcharge(product_defs[pno], opts or {})

    user_ids = {}
    for i, (name, email, password, role) in enumerate(USERS, start=1):
        hashed = auth.hash_password(password)
        line_id = USERS_LINE_ID.get(email, "")
        statements.append(
            "INSERT OR IGNORE INTO users (id, name, email, password_hash, role, line_id, created_at) "
            "VALUES ({}, '{}', '{}', '{}', '{}', '{}', '2026-08-01 08:00:00');".format(
                i, name.replace("'", "''"), email, hashed, role,
                line_id.replace("'", "''"),
            )
        )
        user_ids[email] = i

    vendor_ids = {}
    for i, (name, phone, address, note) in enumerate(VENDORS, start=1):
        statements.append(
            "INSERT INTO vendors (id, name, phone, address, note, created_at) "
            "VALUES ({}, '{}', '{}', '{}', '{}', '2026-08-02 08:00:00');".format(
                i, name.replace("'", "''"), phone.replace("'", "''"),
                address.replace("'", "''"), note.replace("'", "''")
            )
        )
        vendor_ids[name] = i

    for pid, (vid, name, price, note, defs) in enumerate(PRODUCTS, start=1):
        opts_sql = "NULL" if not defs else "'{}'".format(
            optionsmod.dump_defs(defs).replace("'", "''")
        )
        statements.append(
            "INSERT INTO products (id, vendor_id, name, price, note, options, created_at) "
            "VALUES ({}, {}, '{}', {}, '{}', {}, '2026-08-02 09:00:00');".format(
                pid, vid, name.replace("'", "''"), price, note.replace("'", "''"), opts_sql
            )
        )

    item_id = 0
    pay_id = 0
    for o in ORDERS:
        oid = o["no"]
        created_by = user_ids[o["created_by"]]
        statements.append(
            "INSERT INTO group_orders (id, title, vendor_id, order_date, deadline, status, note, created_by, created_at) "
            "VALUES ({}, '{}', {}, '{}', '{}', '{}', '{}', {}, '{}');".format(
                oid, o["title"].replace("'", "''"), o["vendor_id"],
                o["order_date"], o["deadline"], o["status"],
                o["note"].replace("'", "''"), created_by, o["created_at"],
            )
        )
        for (email, pno, qty, opts) in o["items"]:
            item_id += 1
            price = unit_price(pno, opts)
            opts_sql = "'{}'".format(optionsmod.dump_options(opts or {}).replace("'", "''"))
            statements.append(
                "INSERT INTO order_items (id, order_id, user_id, product_id, quantity, unit_price, options, created_at) "
                "VALUES ({}, {}, {}, {}, {}, {}, {}, '{}');".format(
                    item_id, oid, user_ids[email], pno, qty, price, opts_sql, o["created_at"]
                )
            )
        for (email, status, method, paid_at) in o["payments"]:
            pay_id += 1
            amount = sum(unit_price(pno, opts) * qty for (e2, pno, qty, opts) in o["items"] if e2 == email)
            statements.append(
                "INSERT INTO payments (id, order_id, user_id, amount, status, method, paid_at, updated_at) "
                "VALUES ({}, {}, {}, {}, '{}', '{}', {}, '{}');".format(
                    pay_id, oid, user_ids[email], amount, status, method,
                    "NULL" if paid_at is None else "'{}'".format(paid_at), o["created_at"],
                )
            )

    for nid, (email, title, message, read) in enumerate(NOTIFICATIONS, start=1):
        statements.append(
            "INSERT INTO notifications (id, user_id, title, message, read, created_at) "
            "VALUES ({}, {}, '{}', '{}', {}, '2026-08-14 04:10:00');".format(
                nid, user_ids[email], title.replace("'", "''"),
                message.replace("'", "''"), read,
            )
        )

    for rid, (ono, email, channel, status, detail) in enumerate(REMINDER_LOGS, start=1):
        statements.append(
            "INSERT INTO reminder_logs (id, order_id, user_id, channel, status, detail, created_at) "
            "VALUES ({}, {}, {}, '{}', '{}', '{}', '2026-08-14 04:10:00');".format(
                rid, ono, user_ids[email], channel, status, detail.replace("'", "''"),
            )
        )
    return statements


def run_local(db_path):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    for stmt in build_sql():
        cur.executescript(stmt)
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="建立測試用範例資料")
    parser.add_argument("--db", default=str(ROOT / "data" / "team-order.db"), help="本地 SQLite 路徑")
    parser.add_argument("--sql", default="", help="額外產出 SQL 檔路徑（供 D1 匯入）")
    parser.add_argument("--reset", action="store_true", help="先刪除既有本地資料庫再重建")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.reset and db_path.exists():
        db_path.unlink()
        print("已刪除舊資料庫:", db_path)

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
        except Exception:
            cnt = 0
        conn.close()
        if cnt > 0:
            print("資料庫已含有資料（vendors={}）。若要重新建立，請先刪除檔案或加 --reset。".format(cnt))
            sys.exit(1)

    statements = build_sql()

    if args.sql:
        out = Path(args.sql)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("-- 測試用範例資料（自動產生）\n" + "\n".join(statements) + "\n", encoding="utf-8")
        print("SQL 已寫出:", out)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_local(db_path)
    print("範例資料已寫入:", db_path)
    print()
    print("帳號:")
    print("  管理員  admin@example.com / admin12345")
    print("  成員    chen@example.com / pass12345  (陳小明, 週五午餐團未付款)")
    print("  成員    lin@example.com  / pass12345  (林小美)")
    print("  成員    zhang@example.com / pass12345 (張大頭, 週五午餐團未付款)")
    print()
    print("範例訂單:")
    for o in ORDERS:
        print("  #{} [{}] {} - {}項商品".format(o["no"], o["status"], o["title"], len(o["items"])))


if __name__ == "__main__":
    main()