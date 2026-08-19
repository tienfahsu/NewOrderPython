"""金額與收款相關的計算與資料操作。"""


async def user_totals(db, order_id):
    """回傳 { user_id: { total, user_name, email, has_line } }（依目前 order_items 計算）。"""
    rows = await db.all(
        """
        SELECT oi.user_id, u.name AS user_name, u.email,
               COALESCE(u.line_user_id, '') AS line_user_id,
               SUM(oi.quantity * oi.unit_price) AS total
        FROM order_items oi
        JOIN users u ON u.id = oi.user_id
        WHERE oi.order_id = ?
        GROUP BY oi.user_id, u.name, u.email, u.line_user_id
        """,
        order_id,
    )
    out = {}
    for r in rows:
        out[r["user_id"]] = {
            "user_id": r["user_id"],
            "user_name": r["user_name"],
            "email": r["email"] or "",
            "has_line": bool(r["line_user_id"]),
            "total": int(r["total"] or 0),
        }
    return out


async def ensure_payment(db, order_id, user_id):
    """確保 payments 有該 (order, user) 的列，金額以目前 items 為準。"""
    totals = await user_totals(db, order_id)
    total = totals.get(user_id, {}).get("total", 0)
    await db.run(
        """
        INSERT INTO payments (order_id, user_id, amount, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(order_id, user_id) DO UPDATE SET
          amount = excluded.amount, updated_at = datetime('now')
        """,
        order_id,
        user_id,
        total,
    )
    row = await db.first(
        "SELECT * FROM payments WHERE order_id = ? AND user_id = ?",
        order_id,
        user_id,
    )
    return row


async def close_order(db, order_id):
    """結單：依目前 items 重建每位用戶的收款金額，未付的維持 unpaid。"""
    totals = await user_totals(db, order_id)
    for uid, info in totals.items():
        await db.run(
            """
            INSERT INTO payments (order_id, user_id, amount, status, updated_at)
            VALUES (?, ?, ?, 'unpaid', datetime('now'))
            ON CONFLICT(order_id, user_id) DO UPDATE SET
              amount = excluded.amount, updated_at = datetime('now')
            """,
            order_id,
            uid,
            info["total"],
        )
    # 已結單後才新增商品的使用者，補上收款列
    item_users = await db.all(
        "SELECT DISTINCT user_id FROM order_items WHERE order_id = ?", order_id
    )
    for r in item_users:
        await ensure_payment(db, order_id, r["user_id"])
    return totals


async def reopen_order(db, order_id):
    """重新開單：將 pending 以外的付款狀態保留，方便再編輯。"""
    await db.run(
        "UPDATE payments SET status = 'unpaid', updated_at = datetime('now') "
        "WHERE order_id = ? AND status = 'pending'",
        order_id,
    )


async def payment_board(db, order_id):
    """回傳收款看板：每位用戶的應付、實付狀態。"""
    totals = await user_totals(db, order_id)
    rows = await db.all(
        """
        SELECT p.*, u.name AS user_name
        FROM payments p
        JOIN users u ON u.id = p.user_id
        WHERE p.order_id = ?
        ORDER BY u.name
        """,
        order_id,
    )
    board = []
    for r in rows:
        uid = r["user_id"]
        info = totals.get(uid, {})
        board.append(
            {
                "id": r["id"],
                "order_id": r["order_id"],
                "user_id": uid,
                "user_name": r["user_name"],
                "amount": int(r["amount"] or 0),
                "live_total": int(info.get("total", r["amount"] or 0)),
                "status": r["status"],
                "method": r["method"] or "",
                "paid_at": r["paid_at"],
                "has_line": bool(info.get("has_line")),
                "email": info.get("email", ""),
                "linepay_transaction_id": r["linepay_transaction_id"] or "",
            }
        )
    # 有訂但還沒有 payments 列的用戶一併列出
    seen = {r["user_id"] for r in rows}
    for uid, info in totals.items():
        if uid not in seen:
            row = await ensure_payment(db, order_id, uid)
            board.append(
                {
                    "id": row["id"],
                    "order_id": order_id,
                    "user_id": uid,
                    "user_name": info["user_name"],
                    "amount": int(row["amount"] or 0),
                    "live_total": int(info["total"] or 0),
                    "status": row["status"],
                    "method": "",
                    "paid_at": None,
                    "has_line": info["has_line"],
                    "email": info["email"],
                    "linepay_transaction_id": "",
                }
            )
    board.sort(key=lambda x: x["user_name"])
    return board
