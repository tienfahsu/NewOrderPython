"""冒煙測試：用 sqlite3 mock 掉 D1 binding，驗證 entry.py 的完整業務流程。

執行： .venv\\Scripts\\python.exe tests\\smoke_test.py
"""

import asyncio
import json
import sqlite3
import sys
import types
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


# ---------- mock workers module ----------
class _Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    @classmethod
    def json(cls, data, status=200, headers=None):
        return cls(json.dumps(data, ensure_ascii=False), status=status, headers=headers or {})

    def __repr__(self):
        return "_Response(status={}, body={})".format(self.status, self.body[:200])


class _WorkerEntrypoint:
    def __init__(self):
        self.env = None
        self.ctx = None


workers_mod = types.ModuleType("workers")
workers_mod.Response = _Response
workers_mod.WorkerEntrypoint = _WorkerEntrypoint
sys.modules["workers"] = workers_mod


# ---------- mock D1 binding ----------
class _Stmt:
    def __init__(self, conn, sql, params=()):
        self.conn = conn
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return _Stmt(self.conn, self.sql, params)

    async def all(self):
        cur = self.conn.execute(self.sql, self.params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return {"results": rows}

    async def run(self):
        cur = self.conn.execute(self.sql, self.params)
        return {"results": [], "meta": {"last_row_id": cur.lastrowid}}


class _MockDB:
    def __init__(self, conn):
        self.conn = conn

    def prepare(self, sql):
        return _Stmt(self.conn, sql)

    async def exec(self, sql):
        self.conn.executescript(sql)


# ---------- mock Request ----------
class _MockHeaders:
    def __init__(self, headers):
        self._headers = headers

    def get(self, key, default=None):
        return self._headers.get(key, default)


class _MockRequest:
    def __init__(self, method, path, body=None, headers=None, url_scheme="http", netloc="test.local"):
        self.method = method
        self.url = "{}://{}{}".format(url_scheme, netloc, path)
        self._body = body
        self._headers = {"cookie": "", **({} if headers is None else headers)}
        self.headers = _MockHeaders(self._headers)

    async def json(self):
        return self._body

    async def text(self):
        return json.dumps(self._body)


# ---------- helpers ----------
def make_env(conn, vars_dict=None):
    class Env:
        def __init__(self):
            self.DB = _MockDB(conn)
            self._vars = {
                "SESSION_SECRET": "test-secret",
                "APP_NAME": "測試",
                **(vars_dict or {}),
            }

        def __getitem__(self, k):
            if k == "DB":
                return self.DB
            if k in self._vars:
                return self._vars[k]
            raise KeyError(k)

    return Env()


async def call(w, method, path, body=None, cookie=None):
    headers = {}
    if cookie:
        headers["cookie"] = "session=" + cookie
    req = _MockRequest(method, path, body, headers)
    return await w.fetch(req)


def main():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    import entry
    w = entry.Default()
    w.env = make_env(conn)
    w.ctx = None

    async def run():
        # 1) 註冊第一位使用者 → 成為管理員
        r = await call(w, "POST", "/api/auth/register", {
            "name": "管理員", "email": "admin@test.com", "password": "pass123",
        })
        assert r.status == 200, r

        # 2) 登入 → 取得 cookie
        r = await call(w, "POST", "/api/auth/login", {"email": "admin@test.com", "password": "pass123"})
        assert r.status == 200, r
        set_cookie = r.headers["Set-Cookie"]
        cookie = set_cookie.split(";")[0].split("=", 1)[1]

        # 3) 管理員建立成員帳號
        r = await call(w, "POST", "/api/users", {"name": "李四", "email": "li@test.com", "password": "pass123"}, cookie)
        assert r.status == 200, r

        # 4) 註冊第二位成員（需邀請碼，REGISTER_TOKEN 未設定→應該失敗；設定後成功）
        r = await call(w, "POST", "/api/auth/register", {"name": "王五", "email": "wang@test.com", "password": "pass123"})
        assert r.status == 400, r  # 系統已初始化
        w.env = make_env(conn, {"REGISTER_TOKEN": "invite2026"})
        r = await call(w, "POST", "/api/auth/register", {
            "name": "王五", "email": "wang@test.com", "password": "pass123", "register_token": "invite2026",
        })
        assert r.status == 200, r

        # 5) 建立廠商與商品
        r = await call(w, "POST", "/api/vendors", {"name": "便當店", "phone": "02-1234"}, cookie)
        assert r.status == 200, r
        r = await call(w, "POST", "/api/products", {"vendor_id": 1, "name": "雞腿便當", "price": 90}, cookie)
        assert r.status == 200, r
        r = await call(w, "POST", "/api/products", {"vendor_id": 1, "name": "排骨便當", "price": 85}, cookie)
        assert r.status == 200, r

        # 6) 建立訂單
        r = await call(w, "POST", "/api/orders", {"title": "週五午餐團", "vendor_id": 1, "order_date": "2026-08-21"}, cookie)
        assert r.status == 200, r
        oid = json.loads(r.body)["id"]

        # 7) 管理員幫李四點餐 + 自己點餐
        r = await call(w, "POST", "/api/orders/{}/items".format(oid), {"product_id": 1, "quantity": 2, "user_id": 2}, cookie)
        assert r.status == 200, r
        r = await call(w, "POST", "/api/orders/{}/items".format(oid), {"product_id": 1, "quantity": 1}, cookie)
        assert r.status == 200, r

        # 8) 王五登入並點餐
        r = await call(w, "POST", "/api/auth/login", {"email": "wang@test.com", "password": "pass123"})
        wang_cookie = r.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
        r = await call(w, "POST", "/api/orders/{}/items".format(oid), {"product_id": 2, "quantity": 1}, wang_cookie)
        assert r.status == 200, r

        # 9) 訂單明細
        r = await call(w, "GET", "/api/orders/{}".format(oid), cookie=cookie)
        d = json.loads(r.body)
        assert d["order"]["status"] == "open", r.body
        assert len(d["items"]) == 3, d["items"]
        assert d["totals"]["2"]["total"] == 180, d["totals"]
        assert d["totals"]["3"]["total"] == 85, d["totals"]
        assert d["my_payment"] is None or d["is_admin"] is True  # admin 不會有 my_payment
        ps = d["payments_summary"]
        assert ps is not None, d.keys()
        assert ps["paid_total"] == 0 and ps["total_users"] == 3, ps

        # 10) 結單
        r = await call(w, "POST", "/api/orders/{}/close".format(oid), {}, cookie)
        assert r.status == 200, r
        r = await call(w, "GET", "/api/orders/{}".format(oid), cookie=cookie)
        d = json.loads(r.body)
        assert d["order"]["status"] == "closed", r.body

        # 11) 收款看板（管理員）
        r = await call(w, "GET", "/api/orders/{}/payments".format(oid), cookie=cookie)
        d = json.loads(r.body)
        assert d["paid_total"] == 0, d
        assert d["unpaid_total"] == 355, d
        assert len(d["board"]) == 3, d["board"]

        # 12) 現金收款一筆
        board = d["board"]
        pid = board[0]["id"]
        r = await call(w, "POST", "/api/payments/{}/mark-paid".format(pid), {"method": "cash"}, cookie)
        assert r.status == 200, r
        r = await call(w, "GET", "/api/orders/{}/payments".format(oid), cookie=cookie)
        d = json.loads(r.body)
        assert d["paid_total"] == board[0]["amount"], d

        # 12.5) 訂單列表含收款狀態（管理員）
        r = await call(w, "GET", "/api/orders", cookie=cookie)
        od = next(o for o in json.loads(r.body)["orders"] if o["id"] == oid)
        assert od["paid_total"] == board[0]["amount"], od

        # 13) 未設 LINE Pay → 產生付款連結應回 400
        r = await call(w, "POST", "/api/payments/{}/linepay".format(pid), {}, cookie)
        assert r.status == 400, r

        # 14) 催款全部未付款（李四已收款；王五、管理員未付款）
        r = await call(w, "POST", "/api/orders/{}/remind-all".format(oid), {}, cookie)
        d = json.loads(r.body)
        assert d["summary"]["reminded"] == 2, d

        # 14.5) 單一用戶催款：指定管道
        r = await call(w, "GET", "/api/orders/{}/payments".format(oid), cookie=cookie)
        d = json.loads(r.body)
        target = next(b for b in d["board"] if b["status"] != "paid")

        # 管理員為使用者設定 LINE User ID（LINE Messaging API）
        r = await call(w, "GET", "/api/users", cookie=cookie)
        target_user = next(u for u in json.loads(r.body)["users"] if u["id"] == target["user_id"])
        r = await call(w, "PUT", "/api/users/{}".format(target_user["id"]), {"line_user_id": "U-test-user-id"}, cookie)
        assert r.status == 200, r
        r = await call(w, "GET", "/api/users", cookie=cookie)
        updated = next(u for u in json.loads(r.body)["users"] if u["id"] == target_user["id"])
        assert updated["line_user_id"] == "U-test-user-id" and updated["has_line"] is True, updated

        # 管理者可另外設定 LINE ID 名稱（使用者代碼），與推播用的 user_id 獨立
        r = await call(w, "PUT", "/api/users/{}".format(target_user["id"]), {"line_id": "tienfa_hsu"}, cookie)
        assert r.status == 200, r
        r = await call(w, "GET", "/api/users", cookie=cookie)
        updated2 = next(u for u in json.loads(r.body)["users"] if u["id"] == target_user["id"])
        assert updated2["line_id"] == "tienfa_hsu" and updated2["line_user_id"] == "U-test-user-id", updated2

        # 已綁定但未設定任何 LINE 憑證 → 略過並提示
        r = await call(w, "POST", "/api/payments/{}/remind".format(target["id"]), {"channel": "line"}, cookie)
        assert r.status == 200, r
        assert json.loads(r.body)["results"] == [
            {"channel": "line", "status": "skipped", "detail": "no-line-token"}
        ], r.body

        # 尚未綁定的用戶 → 略過
        r = await call(w, "GET", "/api/orders/{}/payments".format(oid), cookie=cookie)
        d2 = json.loads(r.body)
        unbinded = next(b for b in d2["board"] if b["status"] != "paid" and b["user_id"] != target["user_id"])
        r = await call(w, "POST", "/api/payments/{}/remind".format(unbinded["id"]), {"channel": "line"}, cookie)
        assert json.loads(r.body)["results"] == [
            {"channel": "line", "status": "skipped", "detail": "未綁定 LINE"}
        ], r.body

        # 只有 LINE ID 名稱（無 User ID）→ 提示需 U 開頭 User ID
        r = await call(w, "PUT", "/api/users/{}".format(unbinded["user_id"]), {"line_id": "abc_de", "line_user_id": ""}, cookie)
        assert r.status == 200, r
        r = await call(w, "POST", "/api/payments/{}/remind".format(unbinded["id"]), {"channel": "line"}, cookie)
        dline = json.loads(r.body)
        assert dline["results"][0]["detail"] == (
            "LINE User ID 未設定（LINE ID 名稱不能推播，需 U 開頭的 User ID）"
        ), r.body

        # 清掉 LINE User ID
        r = await call(w, "PUT", "/api/users/{}".format(target_user["id"]), {"line_user_id": ""}, cookie)
        assert r.status == 200, r
        r = await call(w, "POST", "/api/payments/{}/remind".format(target["id"]), {"channel": "all"}, cookie)
        rr = json.loads(r.body)
        assert len(rr["results"]) == 3, rr
        assert rr["results"][0]["channel"] == "app" and rr["results"][0]["status"] == "sent", rr

        # 15) 王五看通知
        r = await call(w, "GET", "/api/notifications", cookie=wang_cookie)
        d = json.loads(r.body)
        assert len(d["notifications"]) >= 1, d
        nid = d["notifications"][0]["id"]
        r = await call(w, "POST", "/api/notifications/{}/read".format(nid), {}, wang_cookie)
        assert r.status == 200, r

        # 16) 一般成員不能看收款看板
        r = await call(w, "GET", "/api/orders/{}/payments".format(oid), cookie=wang_cookie)
        assert r.status in (401, 403), r

        # 17) 一般成員在結單後不能改數量
        r = await call(w, "POST", "/api/orders/{}/items".format(oid), {"product_id": 2, "quantity": 2}, wang_cookie)
        assert r.status == 400, r

        # 18) 重新開單
        r = await call(w, "POST", "/api/orders/{}/reopen".format(oid), {}, cookie)
        assert r.status == 200, r
        r = await call(w, "POST", "/api/orders/{}/items".format(oid), {"product_id": 2, "quantity": 2}, wang_cookie)
        assert r.status == 200, r

        # 19) 客製化選項 + 加價（重新開單後）
        r = await call(w, "POST", "/api/products", {
            "vendor_id": 1, "name": "珍珠奶茶", "price": 50,
            "options": [
                {"key": "ice", "label": "冰量", "type": "select", "choices": ["正常冰", "少冰"]},
                {"key": "topping", "label": "加料", "type": "multi",
                 "choices": ["珍珠", "布丁"], "prices": {"珍珠": 10, "布丁": 5}},
            ],
        }, cookie)
        assert r.status == 200, r
        r = await call(w, "GET", "/api/products?active=0", cookie=cookie)
        drink = next(p for p in json.loads(r.body)["products"] if p["name"] == "珍珠奶茶")
        assert drink["options"][1]["prices"]["珍珠"] == 10, drink

        r = await call(w, "POST", "/api/orders/{}/items".format(oid), {
            "product_id": drink["id"], "quantity": 2,
            "options": {"ice": "少冰", "topping": ["珍珠", "布丁"], "bad_key": "x"},
        }, wang_cookie)
        assert r.status == 200, r

        r = await call(w, "GET", "/api/orders/{}".format(oid), cookie=cookie)
        d = json.loads(r.body)
        drink_item = next(it for it in d["items"] if it["product_id"] == drink["id"])
        assert drink_item["unit_price"] == 65, drink_item  # 50 + 10 + 5
        assert drink_item["options"] == {"ice": "少冰", "topping": ["珍珠", "布丁"]}, drink_item
        assert "少冰" in drink_item["options_desc"] and "珍珠" in drink_item["options_desc"], drink_item
        assert d["totals"]["3"]["total"] == 300, d["totals"]  # 85*2(排骨便當) + 65*2

        # 20) 未登入 → 401
        r = await call(w, "GET", "/api/orders")
        assert r.status == 401, r

        # 20.5) 分享（QR 一頁式）流程
        r = await call(w, "POST", "/api/auth/login", {"email": "admin@test.com", "password": "pass123"})
        cookie = r.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
        r = await call(w, "POST", "/api/orders/{}/share".format(oid), {"minutes": 60}, cookie)
        d = json.loads(r.body)
        assert r.status == 200 and d["ok"], r.body
        assert "/#/s/" in d["url"] and d["token"], d
        token = d["token"]

        # 未登入訪客拿 share 資料
        r = await call(w, "GET", "/api/share/{}".format(token))
        d = json.loads(r.body)
        assert r.status == 200, r.body
        assert d["order"]["id"] == oid, d
        assert not d["identified"], d
        assert all("options" in p for v in d["vendors"] for p in v["products"]), d

        # 訪客以自己的電話辨識 → 自動建立會員 + 設 session cookie
        r = await call(w, "POST", "/api/share/{}/identify".format(token), {"identifier": "0999111222"})
        d = json.loads(r.body)
        assert r.status == 200 and d["ok"], r.body
        assert d["is_new"] is True and d["user_name"] == "0999111222", d
        guest_cookie = r.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]

        # 訪客用 share 換到授權後可讀自己的項目（空）
        r = await call(w, "GET", "/api/share/{}/my".format(token), cookie=guest_cookie)
        d = json.loads(r.body)
        assert r.status == 200 and d["my_items"] == [], r.body

        # 訪客用正式 API 點餐（這是 QR 頁面背後的行為）
        r = await call(w, "POST", "/api/orders/{}/items".format(oid), {"product_id": 1, "quantity": 1}, guest_cookie)
        assert r.status == 200, r.body

        # identify 再次以相同電話 → is_new=False，且可看到自己點過的項目
        r = await call(w, "POST", "/api/share/{}/identify".format(token), {"identifier": "0999111222"})
        d = json.loads(r.body)
        assert r.status == 200 and d["is_new"] is False, r.body
        assert len(d["my_items"]) == 1 and d["my_items"][0]["quantity"] == 1, d

        # 用 LINE ID 名稱（使用者代碼）可在分享頁辨識出既有成員
        r = await call(w, "POST", "/api/share/{}/identify".format(token), {"identifier": "tienfa_hsu"})
        d = json.loads(r.body)
        assert r.status == 200 and d["ok"] and d["is_new"] is False, r.body
        assert d["user_name"] == target_user["name"], d  # 前面已把 target_user 的 line_id 設為 tienfa_hsu

        # 無效 token → 404
        r = await call(w, "GET", "/api/share/bad-token")
        assert r.status == 404, r

        # 一般成員不能建立 share token
        r = await call(w, "POST", "/api/auth/login", {"email": "wang@test.com", "password": "pass123"})
        wang_cookie = r.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
        r = await call(w, "POST", "/api/orders/{}/share".format(oid), {}, wang_cookie)
        assert r.status in (401, 403), r

        # 20.6) LINE webhook（未設定 CHANNEL_SECRET → 400）
        import base64, hashlib, hmac as _hmac
        w.env = make_env(conn, {"LINE_CHANNEL_SECRET": "test-secret", "LINE_CHANNEL_ID": "123", "LINE_CHANNEL_SECRET2": ""})
        payload = {"events": [{"type": "follow", "source": {"userId": "U-webhook-test"}}]}
        raw = json.dumps(payload)
        sig = base64.b64encode(
            _hmac.new(b"test-secret", raw.encode("utf-8"), hashlib.sha256).digest()
        ).decode()
        req = _MockRequest("POST", "/api/line/webhook", json.loads(raw), {"x-line-signature": sig})
        r = await w.fetch(req)
        # 無 LINE_CHANNEL_ACCESS_TOKEN 且未以帳號填正式金鑰 → 因網外呼叫跳過，故僅確認不因簽章錯誤被拒
        assert r.status == 200, r.body
        # 簽章錯誤 → 401
        bad_sig = base64.b64encode(b"x").decode()
        req = _MockRequest("POST", "/api/line/webhook", json.loads(raw), {"x-line-signature": bad_sig})
        r = await w.fetch(req)
        assert r.status == 401, r
        w.env = make_env(conn, {"REGISTER_TOKEN": "invite2026", "SESSION_SECRET": "test-secret"})

        # 21) 靜態檔案
        req = _MockRequest("GET", "/")
        r = await w.fetch(req)
        assert r.status == 200 and "訂餐系統" in r.body, r
        req = _MockRequest("GET", "/app.js")
        r = await w.fetch(req)
        assert r.status == 200 and "router" in r.body, r

        print("All {} smoke checks passed.".format(22))

    asyncio.run(run())


if __name__ == "__main__":
    main()