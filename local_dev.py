"""本機執行模式：不需要 Cloudflare / Node.js，直接用 Python 跑同一個 Worker。

用法：
  .venv\\Scripts\\python.exe local_dev.py                # 預設 http://127.0.0.1:8787
  .venv\\Scripts\\python.exe local_dev.py --port 8000

資料存在 data/team-order.db（SQLite）。密鑰會自動讀取 .dev.vars（若存在）。
"""

import argparse
import asyncio
import json
import sqlite3
import sys
import os
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ------------------------------------------------------------------ workers shim
class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    @classmethod
    def json(cls, data, status=200, headers=None):
        return cls(json.dumps(data, ensure_ascii=False), status=status, headers=headers or {})


class WorkerEntrypoint:
    def __init__(self):
        self.env = None
        self.ctx = None


_workers_mod = types.ModuleType("workers")
_workers_mod.Response = Response
_workers_mod.WorkerEntrypoint = WorkerEntrypoint
sys.modules["workers"] = _workers_mod

import entry  # noqa: E402


# --------------------------------------------------------- local D1 (sqlite) binding
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
        return {"results": [dict(zip(cols, r)) for r in cur.fetchall()]}

    async def run(self):
        cur = self.conn.execute(self.sql, self.params)
        self.conn.commit()
        return {"results": [], "meta": {"last_row_id": cur.lastrowid}}


class Binding:
    def __init__(self, conn):
        self.conn = conn

    def prepare(self, sql):
        return _Stmt(self.conn, sql)

    async def exec(self, sql):
        self.conn.executescript(sql)


class Env:
    def __init__(self, conn, vars_dict):
        self.DB = Binding(conn)
        self._vars = vars_dict

    def __getitem__(self, key):
        if key == "DB":
            return self.DB
        if key in self._vars:
            return self._vars[key]
        raise KeyError(key)


def load_env():
    env = {
        "SESSION_SECRET": "local-dev-secret-change-me",
        "APP_NAME": "訂餐系統 (本地)",
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "admin12345",
        "ADMIN_NAME": "系統管理員",
        "LINE_PAY_CHANNEL_ID": "2011164694",
        "LINE_PAY_CHANNEL_SECRET": "222e04c4a4bd7877d8fefe250dd830ec",
    }
    dev_vars = ROOT / ".dev.vars"
    if dev_vars.exists():
        for line in dev_vars.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


# ------------------------------------------------------------- HTTP bridge
class Request:
    def __init__(self, method, path, body_text, headers):
        self.method = method
        self.url = "http://127.0.0.1:{}{}".format(args.port, path)
        self._body_text = body_text
        self._headers = headers

    @property
    def headers(self):
        return self._headers

    async def json(self):
        return json.loads(self._body_text) if self._body_text else {}

    async def text(self):
        return self._body_text


class LocalServer:
    def __init__(self):
        db_path = ROOT / "data" / "team-order.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.loop = asyncio.new_event_loop()
        self.worker = entry.Default()
        self.worker.env = Env(self.conn, load_env())
        self.worker.ctx = None


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        body_text = body.decode("utf-8", errors="replace")
        req = Request(method, self.path, body_text, self.headers)
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.server.worker.fetch(req), self.server.loop
            )
            resp = future.result(timeout=120)
        except Exception as e:
            import traceback

            traceback.print_exc()
            self._write(500, {"error": str(e)})
            return
        data = resp.body
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("  [{}] {}".format(self.command, self.path))


def main():
    global args
    parser = argparse.ArgumentParser(description="本地執行訂餐系統")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = LocalServer()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    httpd.worker = server.worker
    httpd.loop = server.loop

    t = threading.Thread(target=server.loop.run_forever, daemon=True)
    t.start()

    print()
    print("=" * 56)
    print("  訂餐/下午茶系統 — 本地執行中")
    print("  網址: http://127.0.0.1:{}".format(args.port))
    print("  資料: data/team-order.db")
    print("  預設管理員: {} / {}".format(server.worker._env("ADMIN_EMAIL"), server.worker._env("ADMIN_PASSWORD")))
    print("  按 Ctrl+C 停止")
    print("=" * 56)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.loop.call_soon_threadsafe(server.loop.stop)
        t.join()
        httpd.shutdown()


if __name__ == "__main__":
    main()