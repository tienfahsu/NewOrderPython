"""催款通知：系統內通知 + LINE Messaging API + Email (Resend)。"""

import httpx

DEFAULT_TIMEOUT = 15.0

# LINE Messaging API access token 快取（避免每次呼叫都重新換發）
_token_cache = {"token": "", "expires_at": 0}


def env_str(env, name, default=""):
    try:
        v = env[name]
    except Exception:
        try:
            v = getattr(env, name, None)
        except Exception:
            v = None
    if v is None or v == "":
        return default
    return str(v)


async def send_email(resend_key, from_email, to, subject, html):
    if not resend_key or not to:
        return {"ok": False, "detail": "no-email-config"}
    headers = {
        "Authorization": "Bearer {}".format(resend_key),
        "Content-Type": "application/json",
    }
    body = {
        "from": from_email,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.post("https://api.resend.com/emails", headers=headers, json=body)
    return {"ok": resp.status_code < 300, "detail": "http-{}".format(resp.status_code)}


async def _get_channel_access_token(env):
    """取得 LINE Messaging API 的 Channel Access Token。

    優先使用環境變數 LINE_CHANNEL_ACCESS_TOKEN（長期權杖）；
    否則用 LINE_CHANNEL_ID / LINE_CHANNEL_SECRET 透過 OAuth 自動換發
    （有效約 30 天，此處做記憶體快取）。
    """
    token = env_str(env, "LINE_CHANNEL_ACCESS_TOKEN")
    if token:
        return token
    channel_id = env_str(env, "LINE_CHANNEL_ID")
    channel_secret = env_str(env, "LINE_CHANNEL_SECRET")
    if not channel_id or not channel_secret:
        return ""
    import time as _time

    now = _time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                "https://api.line.me/v2/oauth/accessToken",
                data={
                    "grant_type": "client_credentials",
                    "client_id": channel_id,
                    "client_secret": channel_secret,
                },
            )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        expires_in = int(data.get("expires_in") or 0)
        _token_cache["token"] = data.get("access_token", "")
        _token_cache["expires_at"] = now + expires_in
        return _token_cache["token"]
    except Exception:
        return ""


async def send_line_message(env, user_id, message):
    """透過 LINE Messaging API 推播訊息給已綁定使用者。

    需要 LINE_CHANNEL_ACCESS_TOKEN（或 LINE_CHANNEL_ID / LINE_CHANNEL_SECRET
    自動換發）。user_id 為使用者加入機器人好友後由 LINE 提供的 User ID。
    """
    access_token = await _get_channel_access_token(env)
    if not access_token or not user_id:
        return {"ok": False, "detail": "no-line-token"}
    headers = {
        "Authorization": "Bearer {}".format(access_token),
        "Content-Type": "application/json",
    }
    body = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            "https://api.line.me/v2/bot/message/push",
            headers=headers,
            json=body,
        )
    return {"ok": resp.status_code == 200, "detail": "http-{}".format(resp.status_code)}


async def app_notify(db, user_id, title, message):
    await db.run(
        "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
        user_id,
        title,
        message,
    )
    return {"ok": True, "detail": "app"}


async def remind_user(db, env, order, user_row, amount, app_base_url, channels=None):
    """針對單一用戶送出催款。channels 可指定 ["app","line","email"] 子集，預設全部。

    回傳 channels 清單與 reminder_logs 寫入。
    """
    if channels is None:
        channels = ["app", "line", "email"]
    results = []
    order_title = order["title"]
    subject = "【催款通知】{} - 尚未付款".format(order_title)
    body_text = (
        "{name} 您好：\n"
        "您在「{title}」的訂單尚有 NT${amount} 未付款，"
        "請盡速處理，謝謝！\n{url}"
    ).format(
        name=user_row["name"], title=order_title, amount=amount,
        url=app_base_url + "/#/orders/" + str(order["id"]),
    )
    html = (
        "<p>{name} 您好：</p>"
        "<p>您在「<strong>{title}</strong>」的訂單尚有 "
        "<strong style='color:#d33'>NT${amount}</strong> 未付款，請盡速處理，謝謝。</p>"
        "<p><a href='{url}'>{url}</a></p>"
    ).format(
        name=user_row["name"], title=order_title, amount=amount,
        url=app_base_url + "/#/orders/" + str(order["id"]),
    )

    if "app" in channels:
        # 系統內通知
        res = await app_notify(db, user_row["id"], subject, body_text)
        results.append({"channel": "app", "status": "sent" if res["ok"] else "failed", "detail": res["detail"]})

    if "line" in channels:
        # LINE Messaging API
        if user_row.get("line_user_id"):
            res = await send_line_message(env, user_row["line_user_id"], body_text)
            skipped = res["detail"] in ("no-line-token", "no-line-user")
            results.append({
                "channel": "line",
                "status": "skipped" if skipped else ("sent" if res["ok"] else "failed"),
                "detail": res["detail"],
            })
        else:
            if user_row.get("line_id"):
                # 只有 LINE ID 名稱（使用者代碼），沒有可推播的 User ID
                detail = "LINE User ID 未設定（LINE ID 名稱不能推播，需 U 開頭的 User ID）"
            else:
                detail = "未綁定 LINE"
            results.append({"channel": "line", "status": "skipped", "detail": detail})

    if "email" in channels:
        # Email
        resend_key = env_str(env, "RESEND_API_KEY")
        from_email = env_str(env, "DEFAULT_FROM_EMAIL", "team-order@noreply.example.com")
        if resend_key and user_row.get("email"):
            res = await send_email(resend_key, from_email, user_row["email"], subject, html)
            results.append({"channel": "email", "status": "sent" if res["ok"] else "failed", "detail": res["detail"]})
        elif resend_key:
            results.append({"channel": "email", "status": "skipped", "detail": "無 Email 設定"})
        else:
            results.append({"channel": "email", "status": "skipped", "detail": "未設定 RESEND_API_KEY"})

    for r in results:
        await db.run(
            "INSERT INTO reminder_logs (order_id, user_id, channel, status, detail) VALUES (?, ?, ?, ?, ?)",
            order["id"], user_row["id"], r["channel"], r["status"], r["detail"],
        )
    return results