import httpx

BASE = "http://127.0.0.1:8787"
c = httpx.Client(base_url=BASE, timeout=20)

# 管理員登入
r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin12345"})
assert r.status_code == 200, r.text
print("1. admin login OK")

# 廠商列表
r = c.get("/api/vendors")
vs = r.json()["vendors"]
assert len(vs) == 3, vs
print("2. vendors:", [v["name"] for v in vs])

# 訂單列表
r = c.get("/api/orders")
os_ = r.json()["orders"]
assert len(os_) == 3, os_
o1 = next(o for o in os_ if o["id"] == 1)
assert o1["status"] == "closed" and o1["total"] == 645, o1
print("3. orders:", [(o["id"], o["status"], o["total"]) for o in os_])

# 收款看板（結單訂單 #1）
r = c.get("/api/orders/1/payments")
board = r.json()["board"]
assert r.json()["paid_total"] == 275, r.json()
assert r.json()["unpaid_total"] == 370, r.json()
print("4. board #1:", [(b["user_name"], b["amount"], b["status"]) for b in board])

# 催款紀錄
logs = r.json()["reminder_logs"]
assert len(logs) == 6, logs
print("5. reminder_logs:", len(logs))

# 成員登入 + 通知
c2 = httpx.Client(base_url=BASE, timeout=20)
r = c2.post("/api/auth/login", json={"email": "chen@example.com", "password": "pass12345"})
assert r.status_code == 200, r.text
r = c2.get("/api/notifications")
ns = r.json()["notifications"]
assert len(ns) == 1, ns
print("6. chen notifications:", ns[0]["title"])

# 成員在開放訂單 #2 點餐
r = c2.post("/api/orders/2/items", json={"product_id": 8, "quantity": 1})
assert r.status_code == 200, r.text
r = c2.get("/api/orders/2")
d = r.json()
assert d["my_payment"]["total"] == 120, d  # 原本 2 杯四季春(70) + 新加檸檬紅茶(50)
print("7. chen order #2 my total:", d["my_payment"]["total"])

# 管理員可看到成員編輯後的看板
r = c.get("/api/orders/2/payments")
print("8. board #2:", [(b["user_name"], b["live_total"]) for b in r.json()["board"]])

print("ALL SEED CHECKS PASSED")