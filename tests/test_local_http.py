import httpx

BASE = "http://127.0.0.1:8787"
c = httpx.Client(base_url=BASE, timeout=20)

# 1) admin auto-created via .dev.vars defaults
r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin12345"})
assert r.status_code == 200, r.text
admin_cookie = c.cookies.get("session")
print("1. admin login OK")

# 2) create vendor + product
r = c.post("/api/vendors", json={"name": "便當店", "phone": "02-1234"})
assert r.status_code == 200, r.text
r = c.post("/api/products", json={"vendor_id": 1, "name": "雞腿便當", "price": 90})
assert r.status_code == 200, r.text
print("2. vendor/product OK")

# 3) open order + add item
r = c.post("/api/orders", json={"title": "今日午餐", "vendor_id": 1})
oid = r.json()["id"]
r = c.post(f"/api/orders/{oid}/items", json={"product_id": 1, "quantity": 2})
assert r.status_code == 200, r.text
print("3. order + item OK, oid =", oid)

# 4) detail (admin: my_payment 為 None，管理員走收款看板)
r = c.get(f"/api/orders/{oid}")
d = r.json()
assert d["my_items"][0]["quantity"] == 2
assert d["my_payment"] is None
print("4. detail OK, admin my_payment =", d["my_payment"])

# 5) close order -> payment board
r = c.post(f"/api/orders/{oid}/close", json={})
assert r.status_code == 200, r.text
r = c.get(f"/api/orders/{oid}/payments")
d = r.json()
assert d["unpaid_total"] == 180, d
print("5. close + board OK")

# 6) mark paid
pid = d["board"][0]["id"]
r = c.post(f"/api/payments/{pid}/mark-paid", json={"method": "cash"})
assert r.status_code == 200, r.text
r = c.get(f"/api/orders/{oid}/payments")
assert r.json()["paid_total"] == 180
print("6. mark paid OK")

# 7) static page check
r = c.get("/")
assert "訂餐系統" in r.text
print("7. static OK")

print("ALL LOCAL HTTP CHECKS PASSED")