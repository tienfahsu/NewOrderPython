"""辦公室訂餐/下午茶系統 - Cloudflare Workers Python 主入口。

部署需求：D1 binding (DB)、python_workers compatibility flag。
"""

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from workers import Response, WorkerEntrypoint

import auth
import db as dbmod
import linepay
import money
import notify
import options as optionsmod

STATIC_DIR = Path(__file__).parent / "static"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _json(data, status=200, headers=None):
    headers = headers or {}
    headers.setdefault("Content-Type", "application/json; charset=utf-8")
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        headers=headers,
    )


def _error(msg, status=400):
    return _json({"error": msg}, status=status)


def _serve_static(path):
    name = "index.html" if path in ("/", "") else path.lstrip("/")
    if ".." in name or name.startswith("/"):
        return None
    fp = STATIC_DIR / name
    if not fp.exists() or not fp.is_file():
        return None
    ext = fp.suffix.lower()
    return Response(
        fp.read_text(encoding="utf-8"),
        headers={
            "Content-Type": MIME.get(ext, "application/octet-stream"),
            "Cache-Control": "no-store",
        },
    )


def _match(path, template):
    pt = [p for p in path.split("/") if p]
    tt = [p for p in template.split("/") if p]
    if len(pt) != len(tt):
        return None
    params = {}
    for a, b in zip(pt, tt):
        if b.startswith("{"):
            params[b[1:-1]] = a
        elif a != b:
            return None
    return params


def _int(v):
    try:
        return int(v)
    except Exception:
        return None


def _vendor_ids(body):
    """從請求 body 取出商家 id 清單（body.vendor_ids 或單一 vendor_id）。"""
    ids = body.get("vendor_ids")
    if isinstance(ids, list):
        out = []
        for v in ids:
            n = _int(v)
            if n:
                out.append(n)
        return out
    v = _int(body.get("vendor_id"))
    return [v] if v else []


async def _set_order_vendors(db, oid, vendor_ids):
    """重設訂單的商家清單（order_vendors）。"""
    await db.run("DELETE FROM order_vendors WHERE order_id = ?", oid)
    for vid in vendor_ids:
        await db.run(
            "INSERT OR IGNORE INTO order_vendors (order_id, vendor_id) VALUES (?, ?)",
            oid, vid,
        )


def _now_plus(minutes):
    return (datetime.utcnow() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _expired(expires_at):
    if not expires_at:
        return False
    try:
        return datetime.utcnow() > datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False


def _identify_kind(identifier):
    if "@" in identifier:
        return "email"
    if re.fullmatch(r"[+0-9\-\s]{7,20}", identifier):
        return "phone"
    return "line"


async def _match_user(db, kind, identifier):
    if kind == "email":
        return await db.first("SELECT * FROM users WHERE email = ?", identifier)
    if kind == "phone":
        return await db.first("SELECT * FROM users WHERE phone = ?", identifier)
    return await db.first(
        "SELECT * FROM users WHERE line_id = ? OR line_user_id = ?",
        identifier, identifier,
    )


async def _create_guest(db, kind, identifier):
    if kind == "email":
        email = identifier
    else:
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:12]
        email = "guest_{}@guest.local".format(digest)
    pw = secrets.token_urlsafe(12)
    uid = await db.last_id(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'member')",
        identifier, email, auth.hash_password(pw),
    )
    if kind == "phone":
        await db.run("UPDATE users SET phone = ? WHERE id = ?", identifier, uid)
    elif kind == "line":
        await db.run("UPDATE users SET line_id = ? WHERE id = ?", identifier, uid)
    return await db.first("SELECT * FROM users WHERE id = ?", uid)


async def _order_user_items(db, oid, uid):
    """回傳某用戶在訂單中的明細（含選項描述）。"""
    rows = await db.all(
        """
        SELECT oi.id, oi.product_id, p.name AS product_name, oi.quantity,
               oi.unit_price, oi.options, (oi.quantity * oi.unit_price) AS line_total
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ? AND oi.user_id = ?
        ORDER BY p.name
        """,
        oid, uid,
    )
    for it in rows:
        it["options"] = optionsmod.parse_item_options(it.get("options"))
        it["options_desc"] = optionsmod.describe(it["options"])
    return rows


class Default(WorkerEntrypoint):
    # ---------------------------------------------------------------- env
    def _env(self, name, default=""):
        try:
            v = self.env[name]
        except Exception:
            try:
                v = getattr(self.env, name, None)
            except Exception:
                v = None
        if v is None or v == "":
            return default
        return str(v)

    def _db(self):
        return dbmod.DB(self.env.DB)

    def _secret(self):
        return self._env("SESSION_SECRET", "insecure-default-secret-change-me")

    # ---------------------------------------------------------------- fetch
    async def fetch(self, request):
        url = urlparse(request.url)
        path = url.path
        if not path.startswith("/api"):
            if path == "/favicon.ico":
                return Response("", status=404)
            resp = _serve_static(path)
            if resp is not None:
                return resp
            return _serve_static("/") or Response("Not Found", status=404)

        db = self._db()
        try:
            await db.init_schema()
        except Exception as e:
            return _error("資料庫初始化失敗: {}".format(e), 500)
        await self._ensure_admin(db)

        try:
            return await self._route(request, url, path)
        except Exception as e:
            import traceback

            traceback.print_exc()
            return _error("伺服器錯誤: {}".format(e), 500)

    # ---------------------------------------------------------------- auth helpers
    async def _ensure_admin(self, db):
        """若環境變數設定 ADMIN_EMAIL / ADMIN_PASSWORD 且無管理員時，自動建立管理員。"""
        admin_email = self._env("ADMIN_EMAIL")
        admin_password = self._env("ADMIN_PASSWORD")
        if not admin_email or not admin_password:
            return
        existing = await db.first("SELECT id FROM users WHERE role = 'admin'")
        if existing:
            return
        dup = await db.first("SELECT id FROM users WHERE email = ?", admin_email.strip().lower())
        if dup:
            return
        await db.run(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
            self._env("ADMIN_NAME", "系統管理員") or "系統管理員",
            admin_email.strip().lower(),
            auth.hash_password(admin_password),
        )

    async def _current_user(self, request):
        token = auth.get_cookie(request, "session")
        if not token:
            return None
        uid = auth.parse_token(token, self._secret())
        if uid is None:
            return None
        return await self._db().first("SELECT * FROM users WHERE id = ?", uid)

    async def _require_user(self, request):
        user = await self._current_user(request)
        if user is None:
            return None, _error("請先登入", 401)
        return user, None

    async def _require_admin(self, request):
        user = await self._current_user(request)
        if user is None:
            return None, _error("請先登入", 401)
        if user["role"] != "admin":
            return None, _error("需要管理員權限", 403)
        return user, None

    # ---------------------------------------------------------------- router
    async def _route(self, request, url, path):
        method = request.method

        # --- LINE webhook（不需登入，由 LINE 官方呼叫，需簽章驗證）
        m = _match(path, "/api/line/webhook")
        if m is not None and method == "POST":
            return await self._api_line_webhook(request)

        # --- auth
        m = _match(path, "/api/auth/register")
        if m is not None and method == "POST":
            return await self._api_register(request)
        m = _match(path, "/api/auth/login")
        if m is not None and method == "POST":
            return await self._api_login(request)
        m = _match(path, "/api/auth/logout")
        if m is not None and method == "POST":
            return await self._api_logout(request)
        m = _match(path, "/api/auth/me")
        if m is not None and method == "GET":
            return await self._api_me(request)

        # --- users (admin)
        m = _match(path, "/api/users")
        if m is not None and method == "GET":
            return await self._api_users_list(request)
        if m is not None and method == "POST":
            return await self._api_users_create(request)
        m = _match(path, "/api/users/{uid}")
        if m is not None and method == "PUT":
            return await self._api_users_update(request, _int(m["uid"]))
        if m is not None and method == "DELETE":
            return await self._api_users_delete(request, _int(m["uid"]))

        # --- vendors
        m = _match(path, "/api/vendors")
        if m is not None and method == "GET":
            return await self._api_vendors_list(request)
        if m is not None and method == "POST":
            return await self._api_vendors_create(request)
        m = _match(path, "/api/vendors/{vid}")
        if m is not None and method == "PUT":
            return await self._api_vendors_update(request, _int(m["vid"]))
        if m is not None and method == "DELETE":
            return await self._api_vendors_delete(request, _int(m["vid"]))

        # --- products
        m = _match(path, "/api/products")
        if m is not None and method == "GET":
            return await self._api_products_list(request)
        if m is not None and method == "POST":
            return await self._api_products_create(request)
        m = _match(path, "/api/products/{pid}")
        if m is not None and method == "PUT":
            return await self._api_products_update(request, _int(m["pid"]))
        if m is not None and method == "DELETE":
            return await self._api_products_delete(request, _int(m["pid"]))

        # --- orders
        m = _match(path, "/api/orders")
        if m is not None and method == "GET":
            return await self._api_orders_list(request)
        if m is not None and method == "POST":
            return await self._api_orders_create(request)
        m = _match(path, "/api/orders/{oid}/close")
        if m is not None and method == "POST":
            return await self._api_orders_close(request, _int(m["oid"]))
        m = _match(path, "/api/orders/{oid}/reopen")
        if m is not None and method == "POST":
            return await self._api_orders_reopen(request, _int(m["oid"]))
        m = _match(path, "/api/orders/{oid}/remind-all")
        if m is not None and method == "POST":
            return await self._api_orders_remind_all(request, _int(m["oid"]))
        m = _match(path, "/api/orders/{oid}/share")
        if m is not None and method == "POST":
            return await self._api_orders_share_create(request, _int(m["oid"]))
        m = _match(path, "/api/share/{token}/identify")
        if m is not None and method == "POST":
            return await self._api_share_identify(request, m["token"])
        m = _match(path, "/api/share/{token}/my")
        if m is not None and method == "GET":
            return await self._api_share_my(request, m["token"])
        m = _match(path, "/api/share/{token}")
        if m is not None and method == "GET":
            return await self._api_share_info(request, m["token"])
        m = _match(path, "/api/orders/{oid}/payments")
        if m is not None and method == "GET":
            return await self._api_orders_payments(request, _int(m["oid"]))
        m = _match(path, "/api/orders/{oid}/items")
        if m is not None and method == "POST":
            return await self._api_orders_add_item(request, _int(m["oid"]))
        m = _match(path, "/api/orders/{oid}/items/{iid}")
        if m is not None and method == "DELETE":
            return await self._api_orders_del_item(request, _int(m["oid"]), _int(m["iid"]))
        m = _match(path, "/api/orders/{oid}")
        if m is not None and method == "GET":
            return await self._api_orders_detail(request, _int(m["oid"]))
        if m is not None and method == "PUT":
            return await self._api_orders_update(request, _int(m["oid"]))
        if m is not None and method == "DELETE":
            return await self._api_orders_delete(request, _int(m["oid"]))

        # --- payments
        m = _match(path, "/api/payments/linepay/webhook")
        if m is not None and method == "POST":
            return await self._api_linepay_webhook(request)
        m = _match(path, "/api/payments/linepay/callback")
        if m is not None and method == "GET":
            return await self._api_linepay_callback(request)
        m = _match(path, "/api/payments/{pid}/remind")
        if m is not None and method == "POST":
            return await self._api_payments_remind(request, _int(m["pid"]))
        m = _match(path, "/api/payments/{pid}/mark-paid")
        if m is not None and method == "POST":
            return await self._api_payments_mark_paid(request, _int(m["pid"]))
        m = _match(path, "/api/payments/{pid}/unmark")
        if m is not None and method == "POST":
            return await self._api_payments_unmark(request, _int(m["pid"]))
        m = _match(path, "/api/payments/{pid}/linepay")
        if m is not None and method == "POST":
            return await self._api_payments_linepay(request, _int(m["pid"]))
        m = _match(path, "/api/payments/{pid}")
        if m is not None and method == "GET":
            return await self._api_payments_detail(request, _int(m["pid"]))

        # --- notifications
        m = _match(path, "/api/notifications")
        if m is not None and method == "GET":
            return await self._api_notifications_list(request)
        m = _match(path, "/api/notifications/read-all")
        if m is not None and method == "POST":
            return await self._api_notifications_read_all(request)
        m = _match(path, "/api/notifications/{nid}/read")
        if m is not None and method == "POST":
            return await self._api_notifications_read(request, _int(m["nid"]))

        return _error("找不到此路徑: {} {}".format(method, path), 404)

    # ================================================================ auth
    async def _api_register(self, request):
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        name = str(body.get("name", "")).strip()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        token = str(body.get("register_token", "")).strip()

        if not name or not email or not password:
            return _error("姓名、Email、密碼皆為必填")
        if len(password) < 6:
            return _error("密碼至少 6 碼")
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return _error("Email 格式不正確")

        db = self._db()
        expected = self._env("REGISTER_TOKEN")
        has_users = await db.first("SELECT id FROM users LIMIT 1")
        if expected:
            if token != expected:
                return _error("註冊邀請碼錯誤")
        elif has_users:
            return _error("系統已初始化，請由管理員建立帳號")
        # 第一個帳號直接成為管理員
        role = "admin" if not has_users else "member"

        exists = await db.first("SELECT id FROM users WHERE email = ?", email)
        if exists:
            return _error("此 Email 已註冊")
        await db.run(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            name, email, auth.hash_password(password), role,
        )
        return _json({"ok": True, "message": "註冊成功"})

    async def _api_login(self, request):
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        db = self._db()
        user = await db.first("SELECT * FROM users WHERE email = ?", email)
        if not user or not auth.verify_password(password, user["password_hash"]):
            return _error("Email 或密碼錯誤", 401)
        token = auth.make_token(user["id"], self._secret())
        return _json(
            {"ok": True, "user": self._public_user(user)},
            headers={"Set-Cookie": auth.session_cookie(token)},
        )

    async def _api_logout(self, request):
        return _json(
            {"ok": True},
            headers={"Set-Cookie": auth.clear_session_cookie()},
        )

    async def _api_me(self, request):
        user, err = await self._require_user(request)
        if err:
            return err
        unread = await self._db().first(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND read = 0",
            user["id"],
        )
        return _json({"user": self._public_user(user), "unread": int(unread["c"] or 0)})

    def _public_user(self, user):
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "phone": user["phone"] or "",
            "has_line": bool(user.get("line_user_id")),
            "line_user_id": user.get("line_user_id") or "",
            "line_id": user.get("line_id") or "",
        }

    # ================================================================ users
    async def _api_users_list(self, request):
        admin, err = await self._require_admin(request)
        if err:
            return err
        rows = await self._db().all("SELECT * FROM users ORDER BY name")
        return _json({"users": [self._public_user(r) for r in rows]})

    async def _api_users_create(self, request):
        admin, err = await self._require_admin(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        name = str(body.get("name", "")).strip()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        role = "admin" if body.get("role") == "admin" else "member"
        if not name or not email or not password:
            return _error("姓名、Email、密碼皆為必填")
        db = self._db()
        if await db.first("SELECT id FROM users WHERE email = ?", email):
            return _error("此 Email 已存在")
        await db.run(
            "INSERT INTO users (name, email, password_hash, role, line_id, line_user_id) VALUES (?, ?, ?, ?, ?, ?)",
            name, email, auth.hash_password(password), role,
            str(body.get("line_id", "")).strip(),
            str(body.get("line_user_id", "")).strip(),
        )
        return _json({"ok": True})

    async def _api_users_update(self, request, uid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if uid is None:
            return _error("無效的用戶編號")
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        db = self._db()
        user = await db.first("SELECT * FROM users WHERE id = ?", uid)
        if not user:
            return _error("用戶不存在", 404)
        name = str(body.get("name", user["name"])).strip() or user["name"]
        email = str(body.get("email", user["email"])).strip().lower() or user["email"]
        role = body.get("role", user["role"])
        phone = str(body.get("phone", user["phone"] or ""))
        line_user_id = str(body.get("line_user_id", user.get("line_user_id") or ""))
        line_id = str(body.get("line_id", user.get("line_id") or ""))
        if email != user["email"]:
            if await db.first("SELECT id FROM users WHERE email = ? AND id != ?", email, uid):
                return _error("此 Email 已存在")
        if role not in ("admin", "member"):
            role = user["role"]
        await db.run(
            "UPDATE users SET name=?, email=?, role=?, phone=?, line_user_id=?, line_id=? WHERE id=?",
            name, email, role, phone, line_user_id, line_id, uid,
        )
        password = body.get("password")
        if password:
            if len(password) < 6:
                return _error("新密碼至少 6 碼")
            await db.run(
                "UPDATE users SET password_hash=? WHERE id=?",
                auth.hash_password(password), uid,
            )
        return _json({"ok": True})

    async def _api_users_delete(self, request, uid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if uid is None:
            return _error("無效的用戶編號")
        if uid == admin["id"]:
            return _error("不能刪除自己")
        db = self._db()
        await db.run("DELETE FROM notifications WHERE user_id = ?", uid)
        await db.run("DELETE FROM order_items WHERE user_id = ?", uid)
        await db.run("DELETE FROM payments WHERE user_id = ?", uid)
        await db.run("DELETE FROM reminder_logs WHERE user_id = ?", uid)
        await db.run("DELETE FROM users WHERE id = ?", uid)
        return _json({"ok": True})

    # ================================================================ vendors
    async def _api_vendors_list(self, request):
        user, err = await self._require_user(request)
        if err:
            return err
        rows = await self._db().all(
            """
            SELECT v.*, COUNT(p.id) AS product_count
            FROM vendors v
            LEFT JOIN products p ON p.vendor_id = v.id
            GROUP BY v.id ORDER BY v.name
            """
        )
        return _json({"vendors": rows})

    async def _api_vendors_create(self, request):
        admin, err = await self._require_admin(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        name = str(body.get("name", "")).strip()
        if not name:
            return _error("廠商名稱必填")
        await self._db().run(
            "INSERT INTO vendors (name, phone, address, note) VALUES (?, ?, ?, ?)",
            name,
            str(body.get("phone", "")).strip(),
            str(body.get("address", "")).strip(),
            str(body.get("note", "")).strip(),
        )
        return _json({"ok": True})

    async def _api_vendors_update(self, request, vid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if vid is None:
            return _error("無效的廠商編號")
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        db = self._db()
        v = await db.first("SELECT * FROM vendors WHERE id = ?", vid)
        if not v:
            return _error("廠商不存在", 404)
        name = str(body.get("name", v["name"])).strip() or v["name"]
        await db.run(
            "UPDATE vendors SET name=?, phone=?, address=?, note=? WHERE id=?",
            name,
            str(body.get("phone", v["phone"] or "")),
            str(body.get("address", v["address"] or "")),
            str(body.get("note", v["note"] or "")),
            vid,
        )
        return _json({"ok": True})

    async def _api_vendors_delete(self, request, vid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if vid is None:
            return _error("無效的廠商編號")
        db = self._db()
        if await db.first("SELECT id FROM group_orders WHERE vendor_id = ?", vid):
            return _error("此廠商已有訂單，無法刪除")
        await db.run("DELETE FROM products WHERE vendor_id = ?", vid)
        await db.run("DELETE FROM vendors WHERE id = ?", vid)
        return _json({"ok": True})

    # ================================================================ products
    async def _api_products_list(self, request):
        user, err = await self._require_user(request)
        if err:
            return err
        db = self._db()
        q = parse_qs(urlparse(request.url).query)
        vendor_id = _int(q.get("vendor_id", [""])[0])
        active = q.get("active", ["1"])[0] == "0"
        if vendor_id:
            rows = await db.all(
                "SELECT p.*, v.name AS vendor_name FROM products p "
                "JOIN vendors v ON v.id = p.vendor_id WHERE p.vendor_id = ? ORDER BY p.name",
                vendor_id,
            )
        else:
            rows = await db.all(
                "SELECT p.*, v.name AS vendor_name FROM products p "
                "JOIN vendors v ON v.id = p.vendor_id ORDER BY v.name, p.name"
            )
        if not active:
            rows = [r for r in rows if r["active"]]
        for r in rows:
            r["options"] = optionsmod.parse_defs(r.get("options"))
        return _json({"products": rows})

    async def _api_products_create(self, request):
        admin, err = await self._require_admin(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        name = str(body.get("name", "")).strip()
        vendor_id = _int(body.get("vendor_id"))
        price = _int(body.get("price", 0))
        if not name or not vendor_id:
            return _error("商品名稱與廠商必填")
        if price is None or price < 0:
            return _error("價格格式錯誤")
        defs = optionsmod.parse_defs(optionsmod.dump_defs(body.get("options") or []))
        await self._db().run(
            "INSERT INTO products (vendor_id, name, price, note, options) VALUES (?, ?, ?, ?, ?)",
            vendor_id, name, price, str(body.get("note", "")).strip(),
            optionsmod.dump_defs(defs),
        )
        return _json({"ok": True})

    async def _api_products_update(self, request, pid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if pid is None:
            return _error("無效的商品編號")
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        db = self._db()
        p = await db.first("SELECT * FROM products WHERE id = ?", pid)
        if not p:
            return _error("商品不存在", 404)
        name = str(body.get("name", p["name"])).strip() or p["name"]
        price = _int(body.get("price", p["price"]))
        active = 1 if body.get("active", p["active"]) else 0
        if price is None or price < 0:
            return _error("價格格式錯誤")
        options_raw = p["options"]
        if body.get("options") is not None:
            defs = optionsmod.parse_defs(optionsmod.dump_defs(body["options"]))
            options_raw = optionsmod.dump_defs(defs)
        await db.run(
            "UPDATE products SET name=?, price=?, note=?, active=?, options=? WHERE id=?",
            name, price, str(body.get("note", p["note"] or "")), active, options_raw, pid,
        )
        return _json({"ok": True})

    async def _api_products_delete(self, request, pid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if pid is None:
            return _error("無效的商品編號")
        db = self._db()
        if await db.first("SELECT id FROM order_items WHERE product_id = ?", pid):
            await db.run("UPDATE products SET active = 0 WHERE id = ?", pid)
            return _json({"ok": True, "message": "商品已有訂購紀錄，已停用"})
        await db.run("DELETE FROM products WHERE id = ?", pid)
        return _json({"ok": True})

    # ================================================================ orders
    async def _api_orders_list(self, request):
        user, err = await self._require_user(request)
        if err:
            return err
        db = self._db()
        rows = await db.all(
            """
            SELECT g.*, v.name AS vendor_name,
                   (SELECT GROUP_CONCAT(v2.name, '、') FROM order_vendors ov
                      JOIN vendors v2 ON v2.id = ov.vendor_id
                     WHERE ov.order_id = g.id) AS vendor_names,
                   (SELECT COUNT(DISTINCT user_id) FROM order_items oi WHERE oi.order_id = g.id) AS user_count,
                   (SELECT COUNT(*) FROM order_items oi WHERE oi.order_id = g.id) AS item_count,
                   (SELECT COALESCE(SUM(quantity * unit_price), 0) FROM order_items oi WHERE oi.order_id = g.id) AS total,
                   (SELECT COALESCE(SUM(amount), 0) FROM payments p WHERE p.order_id = g.id AND p.status = 'paid') AS paid_total
            FROM group_orders g
            LEFT JOIN vendors v ON v.id = g.vendor_id
            ORDER BY g.id DESC
            """
        )
        my_items = await db.all(
            "SELECT order_id, SUM(quantity * unit_price) AS my_total, COUNT(*) AS my_count "
            "FROM order_items WHERE user_id = ? GROUP BY order_id",
            user["id"],
        )
        my_map = {r["order_id"]: r for r in my_items}
        orders = []
        is_admin = user["role"] == "admin"
        for r in rows:
            mine = my_map.get(r["id"], {})
            item = {
                "id": r["id"],
                "title": r["title"],
                "vendor_name": r["vendor_names"] or r["vendor_name"] or "",
                "order_date": r["order_date"] or "",
                "deadline": r["deadline"] or "",
                "status": r["status"],
                "user_count": int(r["user_count"] or 0),
                "item_count": int(r["item_count"] or 0),
                "total": int(r["total"] or 0),
                "my_total": int(mine.get("my_total") or 0),
                "my_count": int(mine.get("my_count") or 0),
            }
            if is_admin:
                item["paid_total"] = int(r["paid_total"] or 0)
            orders.append(item)
        return _json({"orders": orders})

    async def _api_orders_create(self, request):
        admin, err = await self._require_admin(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        title = str(body.get("title", "")).strip()
        if not title:
            return _error("訂單標題必填")
        vendor_ids = _vendor_ids(body)
        vendor_id = vendor_ids[0] if vendor_ids else None
        oid = await self._db().last_id(
            "INSERT INTO group_orders (title, vendor_id, order_date, deadline, note, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            title, vendor_id,
            str(body.get("order_date", "")).strip(),
            str(body.get("deadline", "")).strip(),
            str(body.get("note", "")).strip(),
            admin["id"],
        )
        if vendor_ids:
            await _set_order_vendors(self._db(), oid, vendor_ids)
        return _json({"ok": True, "id": oid})

    async def _api_orders_update(self, request, oid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        title = str(body.get("title", order["title"])).strip() or order["title"]
        if body.get("vendor_ids") is not None or body.get("vendor_id") is not None:
            vendor_ids = _vendor_ids(body)
            vendor_id = vendor_ids[0] if vendor_ids else None
        else:
            vendor_ids = None
            vendor_id = order["vendor_id"]
        await db.run(
            "UPDATE group_orders SET title=?, vendor_id=?, order_date=?, deadline=?, note=? WHERE id=?",
            title, vendor_id,
            str(body.get("order_date", order["order_date"] or "")),
            str(body.get("deadline", order["deadline"] or "")),
            str(body.get("note", order["note"] or "")),
            oid,
        )
        if vendor_ids is not None:
            await _set_order_vendors(db, oid, vendor_ids)
        return _json({"ok": True})

    async def _api_orders_delete(self, request, oid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        db = self._db()
        await db.run("DELETE FROM order_items WHERE order_id = ?", oid)
        await db.run("DELETE FROM payments WHERE order_id = ?", oid)
        await db.run("DELETE FROM reminder_logs WHERE order_id = ?", oid)
        await db.run("DELETE FROM group_orders WHERE id = ?", oid)
        return _json({"ok": True})

    async def _api_orders_detail(self, request, oid):
        user, err = await self._require_user(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        vendor = await db.first("SELECT * FROM vendors WHERE id = ?", order["vendor_id"])
        vrows = await db.all(
            "SELECT v.id, v.name, v.note FROM order_vendors ov "
            "JOIN vendors v ON v.id = ov.vendor_id WHERE ov.order_id = ? ORDER BY v.name",
            oid,
        )
        if not vrows and vendor:
            vrows = [{"id": vendor["id"], "name": vendor["name"], "note": vendor["note"] or ""}]
        order = dict(order)
        order["vendor_ids"] = [v["id"] for v in vrows]
        vendors = vrows
        vids = [v["id"] for v in vendors]
        if vids:
            placeholders = ",".join("?" * len(vids))
            products = await db.all(
                "SELECT * FROM products WHERE vendor_id IN ({}) AND active = 1 ORDER BY name".format(placeholders),
                *vids,
            )
        else:
            products = []
        for p in products:
            p["options"] = optionsmod.parse_defs(p.get("options"))
        items = await db.all(
            """
            SELECT oi.id, oi.user_id, u.name AS user_name, oi.product_id,
                   p.name AS product_name, oi.quantity, oi.unit_price, oi.options,
                   (oi.quantity * oi.unit_price) AS line_total
            FROM order_items oi
            JOIN users u ON u.id = oi.user_id
            JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = ?
            ORDER BY u.name, p.name
            """,
            oid,
        )
        for it in items:
            it["options"] = optionsmod.parse_item_options(it.get("options"))
            it["options_desc"] = optionsmod.describe(it["options"])
        totals = await money.user_totals(db, oid)
        my_items = [it for it in items if it["user_id"] == user["id"]]
        is_admin = user["role"] == "admin"
        my_payment = None
        payments_summary = None
        if is_admin:
            board = await money.payment_board(db, oid)
            paid_total = sum(b["amount"] for b in board if b["status"] == "paid")
            payments_summary = {
                "board": board,
                "paid_total": paid_total,
                "unpaid_total": sum(b["amount"] for b in board if b["status"] != "paid"),
                "paid_users": sum(1 for b in board if b["status"] == "paid"),
                "total_users": len(board),
            }
        else:
            my_payment = await money.ensure_payment(db, oid, user["id"])
            my_payment["total"] = totals.get(user["id"], {}).get("total", my_payment["amount"])
        return _json(
            {
                "order": order,
                "vendor": vendor,
                "vendors": vendors,
                "products": products,
                "items": items,
                "totals": totals,
                "my_items": my_items,
                "my_payment": my_payment,
                "payments_summary": payments_summary,
                "is_admin": is_admin,
            }
        )

    async def _api_orders_close(self, request, oid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        await money.close_order(db, oid)
        await db.run("UPDATE group_orders SET status = 'closed' WHERE id = ?", oid)
        return _json({"ok": True})

    async def _api_orders_reopen(self, request, oid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        await money.reopen_order(db, oid)
        await db.run("UPDATE group_orders SET status = 'open' WHERE id = ?", oid)
        return _json({"ok": True})

    # ================================================================ share
    async def _api_orders_share_create(self, request, oid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        try:
            body = await request.json()
        except Exception:
            body = {}
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        minutes = _int(body.get("minutes", 60))
        if minutes is None or minutes <= 0 or minutes > 24 * 60:
            return _error("有效期限需在 1~1440 分鐘之間")
        token = secrets.token_urlsafe(24)
        expires_at = _now_plus(minutes)
        await db.run(
            "INSERT INTO share_tokens (token, order_id, created_by, expires_at) VALUES (?, ?, ?, ?)",
            token, oid, admin["id"], expires_at,
        )
        url = urlparse(request.url)
        app_base = "{}://{}".format(url.scheme, url.netloc)
        return _json({
            "ok": True,
            "token": token,
            "url": app_base + "/#/s/" + token,
            "expires_at": expires_at,
        })

    async def _share_order_payload(self, db, token):
        """依 token 回傳一頁式訂單所需資料；失效/過期回傳 None。"""
        st = await db.first("SELECT * FROM share_tokens WHERE token = ?", token)
        if not st:
            return None
        if _expired(st["expires_at"]):
            return None
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", st["order_id"])
        if not order:
            return None
        vrows = await db.all(
            "SELECT v.id, v.name, v.note FROM order_vendors ov "
            "JOIN vendors v ON v.id = ov.vendor_id WHERE ov.order_id = ? ORDER BY v.name",
            order["id"],
        )
        if not vrows:
            vendor = await db.first("SELECT * FROM vendors WHERE id = ?", order["vendor_id"])
            vrows = [{"id": vendor["id"], "name": vendor["name"], "note": vendor["note"] or ""}] if vendor else []
        vids = [v["id"] for v in vrows]
        if vids:
            placeholders = ",".join("?" * len(vids))
            products = await db.all(
                "SELECT * FROM products WHERE vendor_id IN ({}) AND active = 1 ORDER BY name".format(placeholders),
                *vids,
            )
        else:
            products = []
        for p in products:
            p["options"] = optionsmod.parse_defs(p.get("options"))
        vendor_map = {v["id"]: dict(v, products=[]) for v in vrows}
        for p in products:
            if p["vendor_id"] in vendor_map:
                vendor_map[p["vendor_id"]]["products"].append(p)
        return {
            "order": {
                "id": order["id"],
                "title": order["title"],
                "note": order["note"] or "",
                "status": order["status"],
                "deadline": order["deadline"] or "",
            },
            "vendors": list(vendor_map.values()),
        }

    async def _api_share_info(self, request, token):
        if not token:
            return _error("連結不存在或已失效", 404)
        db = self._db()
        payload = await self._share_order_payload(db, token)
        if not payload:
            return _error("連結不存在或已失效", 404)
        user = await self._current_user(request)
        if user:
            payload["my_items"] = await _order_user_items(db, payload["order"]["id"], user["id"])
            payload["user_name"] = user["name"]
        else:
            payload["my_items"] = []
            payload["user_name"] = ""
        payload["identified"] = bool(user)
        return _json(payload)

    async def _api_share_identify(self, request, token):
        if not token:
            return _error("連結不存在或已失效", 404)
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        identifier = str(body.get("identifier", "")).strip()
        if not identifier:
            return _error("請輸入電話 / Email 或 LINE 辨識碼")
        db = self._db()
        payload = await self._share_order_payload(db, token)
        if not payload:
            return _error("連結不存在或已失效", 404)
        kind = _identify_kind(identifier)
        user = await _match_user(db, kind, identifier)
        is_new = False
        if user is None:
            user = await _create_guest(db, kind, identifier)
            is_new = True
        my_items = await _order_user_items(db, payload["order"]["id"], user["id"])
        session_token = auth.make_token(user["id"], self._secret())
        return _json(
            {
                "ok": True,
                "user_name": user["name"],
                "is_new": is_new,
                "my_items": my_items,
            },
            headers={"Set-Cookie": auth.session_cookie(session_token)},
        )

    async def _api_share_my(self, request, token):
        if not token:
            return _error("連結不存在或已失效", 404)
        user, err = await self._require_user(request)
        if err:
            return err
        db = self._db()
        st = await db.first("SELECT * FROM share_tokens WHERE token = ?", token)
        if not st or _expired(st["expires_at"]):
            return _error("連結不存在或已失效", 404)
        my_items = await _order_user_items(db, st["order_id"], user["id"])
        return _json({"ok": True, "user_name": user["name"], "my_items": my_items})

    async def _api_orders_add_item(self, request, oid):
        user, err = await self._require_user(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        product_id = _int(body.get("product_id"))
        quantity = _int(body.get("quantity", 1))
        target_user_id = user["id"]
        if user["role"] == "admin" and body.get("user_id"):
            target_user_id = _int(body["user_id"]) or user["id"]
        if product_id is None or quantity is None:
            return _error("參數錯誤")
        product = await db.first("SELECT * FROM products WHERE id = ?", product_id)
        if not product:
            return _error("商品不存在", 404)
        if quantity <= 0:
            await db.run(
                "DELETE FROM order_items WHERE order_id=? AND user_id=? AND product_id=?",
                oid, target_user_id, product_id,
            )
            return _json({"ok": True, "deleted": True})
        if order["status"] != "open" and user["role"] != "admin":
            return _error("此訂單已結單，無法再修改")
        product_defs = optionsmod.parse_defs(product.get("options"))
        selected = optionsmod.sanitize_options(product_defs, body.get("options"))
        unit_price = product["price"] + optionsmod.compute_surcharge(product_defs, selected)
        await db.run(
            """
            INSERT INTO order_items (order_id, user_id, product_id, quantity, unit_price, options)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id, user_id, product_id) DO UPDATE SET
              quantity = excluded.quantity, unit_price = excluded.unit_price,
              options = excluded.options
            """,
            oid, target_user_id, product_id, quantity, unit_price,
            optionsmod.dump_options(selected),
        )
        return _json({"ok": True})

    async def _api_orders_del_item(self, request, oid, iid):
        user, err = await self._require_user(request)
        if err:
            return err
        if oid is None or iid is None:
            return _error("參數錯誤")
        db = self._db()
        item = await db.first("SELECT * FROM order_items WHERE id = ?", iid)
        if not item or item["order_id"] != oid:
            return _error("找不到該明細", 404)
        if item["user_id"] != user["id"] and user["role"] != "admin":
            return _error("無權限刪除他人的明細", 403)
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if order and order["status"] != "open" and user["role"] != "admin":
            return _error("此訂單已結單，無法再修改")
        await db.run("DELETE FROM order_items WHERE id = ?", iid)
        return _json({"ok": True})

    async def _api_orders_payments(self, request, oid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        board = await money.payment_board(db, oid)
        logs = await db.all(
            "SELECT * FROM reminder_logs WHERE order_id = ? ORDER BY id DESC LIMIT 100", oid
        )
        paid_total = sum(b["amount"] for b in board if b["status"] == "paid")
        unpaid_total = sum(b["amount"] for b in board if b["status"] != "paid")
        return _json(
            {
                "order": order,
                "board": board,
                "reminder_logs": logs,
                "paid_total": paid_total,
                "unpaid_total": unpaid_total,
            }
        )

    async def _api_orders_remind_all(self, request, oid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if oid is None:
            return _error("無效的訂單編號")
        db = self._db()
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", oid)
        if not order:
            return _error("訂單不存在", 404)
        board = await money.payment_board(db, oid)
        url = urlparse(request.url)
        app_base = "{}://{}".format(url.scheme, url.netloc)
        summary = {"reminded": 0, "skipped": 0}
        details = []
        for b in board:
            if b["status"] == "paid":
                continue
            urow = await db.first("SELECT * FROM users WHERE id = ?", b["user_id"])
            if not urow:
                continue
            amount = b["live_total"] if b["live_total"] > 0 else b["amount"]
            if amount <= 0:
                summary["skipped"] += 1
                continue
            results = await notify.remind_user(db, self.env, order, urow, amount, app_base)
            details.append({"user": b["user_name"], "results": results})
            summary["reminded"] += 1
        return _json({"ok": True, "summary": summary, "details": details})

    # ================================================================ LINE webhook
    async def _api_line_webhook(self, request):
        """LINE Messaging API webhook。

        用途：當使用者加入機器人好友或傳訊息時，回覆其 User ID，
        方便管理員把 User ID 填入該成員帳號以啟用 LINE 催款通知。
        """
        channel_secret = self._env("LINE_CHANNEL_SECRET")
        if not channel_secret:
            return _error("未設定 LINE_CHANNEL_SECRET")
        import json as _json_mod

        raw = await request.text()
        signature = request.headers.get("x-line-signature") or ""
        if not linepay.verify_webhook(channel_secret, raw, signature):
            return _error("簽章驗證失敗", 401)
        try:
            payload = _json_mod.loads(raw)
        except Exception:
            return _json({"ok": False})
        db = self._db()
        for ev in payload.get("events", []):
            etype = ev.get("type")
            src = ev.get("source", {})
            uid = src.get("userId") or ""
            reply_token = ev.get("replyToken") or ""
            if etype == "follow" and uid:
                reply = ("感謝加入好友！\n"
                         "請開啟訂餐系統 → 帳號管理，把以下「LINE User ID」"
                         "填入你的帳號以啟用 LINE 催款通知：\n\n"
                         "{}").format(uid)
                await notify.send_line_message(self.env, uid, reply)
            elif etype == "message" and reply_token and uid:
                msg = ev.get("message", {})
                if msg.get("type") == "text":
                    text = str(msg.get("text") or "").strip()
                    if text.lower() in ("id", "userid", "我的id", "我的 user id"):
                        await notify.send_line_message(
                            self.env, uid, "你的 LINE User ID 是：\n\n{}".format(uid)
                        )
        return _json({"ok": True})

    # ================================================================ payments
    async def _api_payments_remind(self, request, pid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if pid is None:
            return _error("無效的收款編號")
        try:
            body = await request.json()
        except Exception:
            body = {}
        db = self._db()
        pay = await db.first("SELECT * FROM payments WHERE id = ?", pid)
        if not pay:
            return _error("收款紀錄不存在", 404)
        if pay["status"] == "paid":
            return _error("該成員已付款，不需催款")
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", pay["order_id"])
        if not order:
            return _error("訂單不存在", 404)
        urow = await db.first("SELECT * FROM users WHERE id = ?", pay["user_id"])
        if not urow:
            return _error("用戶不存在", 404)
        totals = await money.user_totals(db, pay["order_id"])
        total = int(totals.get(pay["user_id"], {}).get("total", pay["amount"] or 0))
        amount = total if total > 0 else int(pay["amount"] or 0)
        if amount <= 0:
            return _error("金額為 0，無需催款")
        channel = str(body.get("channel", "all"))
        if channel == "all":
            channels = ["app", "line", "email"]
        elif channel in ("app", "line", "email"):
            channels = [channel]
        else:
            return _error("無效的催款管道")
        url = urlparse(request.url)
        app_base = "{}://{}".format(url.scheme, url.netloc)
        results = await notify.remind_user(db, self.env, order, urow, amount, app_base, channels)
        return _json({"ok": True, "results": results, "amount": amount, "user_name": urow["name"]})

    async def _api_payments_detail(self, request, pid):
        user, err = await self._require_user(request)
        if err:
            return err
        if pid is None:
            return _error("無效的收款編號")
        db = self._db()
        pay = await db.first("SELECT * FROM payments WHERE id = ?", pid)
        if not pay:
            return _error("收款紀錄不存在", 404)
        if pay["user_id"] != user["id"] and user["role"] != "admin":
            return _error("無權限", 403)
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", pay["order_id"])
        totals = await money.user_totals(db, pay["order_id"])
        total = int(totals.get(pay["user_id"], {}).get("total", pay["amount"]))
        linepay_configured = bool(self._env("LINE_PAY_CHANNEL_ID"))
        return _json(
            {
                "payment": {
                    "id": pay["id"],
                    "order_id": pay["order_id"],
                    "order_title": order["title"] if order else "",
                    "user_id": pay["user_id"],
                    "amount": int(pay["amount"]),
                    "total": total,
                    "status": pay["status"],
                    "method": pay["method"] or "",
                    "paid_at": pay["paid_at"],
                    "linepay_transaction_id": pay["linepay_transaction_id"] or "",
                },
                "linepay_configured": linepay_configured,
            }
        )

    async def _api_payments_mark_paid(self, request, pid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if pid is None:
            return _error("無效的收款編號")
        try:
            body = await request.json()
        except Exception:
            return _error("JSON 格式錯誤")
        db = self._db()
        pay = await db.first("SELECT * FROM payments WHERE id = ?", pid)
        if not pay:
            return _error("收款紀錄不存在", 404)
        method = str(body.get("method", "other")).strip() or "other"
        await db.run(
            "UPDATE payments SET status='paid', method=?, paid_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
            method, pid,
        )
        return _json({"ok": True})

    async def _api_payments_unmark(self, request, pid):
        admin, err = await self._require_admin(request)
        if err:
            return err
        if pid is None:
            return _error("無效的收款編號")
        await self._db().run(
            "UPDATE payments SET status='unpaid', method='', updated_at=datetime('now') WHERE id=?",
            pid,
        )
        return _json({"ok": True})

    async def _api_payments_linepay(self, request, pid):
        user, err = await self._require_user(request)
        if err:
            return err
        if pid is None:
            return _error("無效的收款編號")
        db = self._db()
        pay = await db.first("SELECT * FROM payments WHERE id = ?", pid)
        if not pay:
            return _error("收款紀錄不存在", 404)
        if pay["user_id"] != user["id"] and user["role"] != "admin":
            return _error("無權限", 403)
        if pay["status"] == "paid":
            return _error("此筆已付款")
        channel_id = self._env("LINE_PAY_CHANNEL_ID")
        channel_secret = self._env("LINE_PAY_CHANNEL_SECRET")
        if not channel_id or not channel_secret:
            return _error("尚未設定 LINE Pay 金流，請改用現金/轉帳收款")
        order = await db.first("SELECT * FROM group_orders WHERE id = ?", pay["order_id"])
        totals = await money.user_totals(db, pay["order_id"])
        amount = int(totals.get(pay["user_id"], {}).get("total", pay["amount"]))
        if amount <= 0:
            return _error("應付金額為 0，無需付款")
        url = urlparse(request.url)
        app_base = "{}://{}".format(url.scheme, url.netloc)
        confirm_url = app_base + "/api/payments/linepay/callback"
        cancel_url = app_base + "/#/orders/" + str(pay["order_id"])
        order_id_str = "T{}-{}".format(pay["order_id"], pay["id"])
        status, data = await linepay.reserve(
            channel_id, channel_secret, amount, order_id_str,
            order["title"] if order else "訂單付款",
            confirm_url, cancel_url,
        )
        if status >= 300 or data.get("returnCode") != "0000":
            return _error("LINE Pay 建立付款失敗: {}".format(data.get("returnMessage", data)), 502)
        info = data["info"]
        await db.run(
            "UPDATE payments SET status='pending', linepay_transaction_id=?, linepay_access_token=?, "
            "amount=?, updated_at=datetime('now') WHERE id=?",
            str(info.get("transactionId", "")),
            info.get("paymentAccessToken", ""),
            amount,
            pid,
        )
        return _json({"ok": True, "paymentUrl": info["paymentUrl"], "transactionId": info.get("transactionId")})

    async def _api_linepay_callback(self, request):
        q = parse_qs(urlparse(request.url).query)
        transaction_id = (q.get("transactionId") or q.get("transactionid") or [""])[0]
        if not transaction_id:
            return _error("缺少 transactionId")
        channel_id = self._env("LINE_PAY_CHANNEL_ID")
        channel_secret = self._env("LINE_PAY_CHANNEL_SECRET")
        if not channel_id or not channel_secret:
            return Response("尚未設定 LINE Pay", status=502)
        db = self._db()
        pay = await db.first("SELECT * FROM payments WHERE linepay_transaction_id = ?", transaction_id)
        if pay and pay["status"] != "paid":
            status, data = await linepay.confirm(
                channel_id, channel_secret, transaction_id, pay["amount"]
            )
            if status < 300 and data.get("returnCode") == "0000":
                await db.run(
                    "UPDATE payments SET status='paid', method='linepay', paid_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
                    pay["id"],
                )
                await db.run(
                    "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
                    pay["user_id"], "付款成功",
                    "您的訂單付款已完成，謝謝！",
                )
        oid = pay["order_id"] if pay else 0
        return Response(
            "<html><meta charset='utf-8'><body><script>location.href='/#/orders/{}/?lp=ok'</script></body></html>".format(oid),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    async def _api_linepay_webhook(self, request):
        channel_secret = self._env("LINE_PAY_CHANNEL_SECRET")
        if not channel_secret:
            return _json({"ok": False, "message": "not configured"}, 200)
        raw = await request.text()
        signature = request.headers.get("x-line-signature") or ""
        if not linepay.verify_webhook(channel_secret, raw, signature):
            return _json({"ok": False, "message": "invalid signature"}, 401)
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        # LINE Pay v3 webhook 常見格式（部分欄位可能為巢狀）
        transaction_id = data.get("transactionId") or data.get("transaction_id")
        status = data.get("status", "")
        if not transaction_id:
            for ev in (data.get("payments") or data.get("events") or []):
                if isinstance(ev, dict):
                    transaction_id = ev.get("transactionId") or ev.get("transaction_id") or transaction_id
                    status = ev.get("status", status)
        if not transaction_id:
            return _json({"ok": True, "message": "ignored"}, 200)
        db = self._db()
        pay = await db.first("SELECT * FROM payments WHERE linepay_transaction_id = ?", str(transaction_id))
        if pay:
            if str(status).upper() in ("CONFIRMED", "PAID", "SUCCESS"):
                await db.run(
                    "UPDATE payments SET status='paid', method='linepay', paid_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
                    pay["id"],
                )
            elif str(status).upper() in ("REFUNDED", "FAILED", "CANCELLED"):
                await db.run(
                    "UPDATE payments SET status='unpaid', updated_at=datetime('now') WHERE id=?",
                    pay["id"],
                )
        return _json({"ok": True}, 200)

    # ================================================================ notifications
    async def _api_notifications_list(self, request):
        user, err = await self._require_user(request)
        if err:
            return err
        rows = await self._db().all(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 200",
            user["id"],
        )
        return _json({"notifications": rows})

    async def _api_notifications_read(self, request, nid):
        user, err = await self._require_user(request)
        if err:
            return err
        if nid is None:
            return _error("無效的通知編號")
        await self._db().run(
            "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
            nid, user["id"],
        )
        return _json({"ok": True})

    async def _api_notifications_read_all(self, request):
        user, err = await self._require_user(request)
        if err:
            return err
        await self._db().run(
            "UPDATE notifications SET read = 1 WHERE user_id = ?",
            user["id"],
        )
        return _json({"ok": True})