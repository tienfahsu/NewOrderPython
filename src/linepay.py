"""LINE Pay v3 整合：建立付款、確認付款、webhook 簽章驗證。

需要 LINE Pay 商家帳號，於後台取得 Channel ID / Channel Secret。
若未設定相關密鑰，系統仍可使用「內部收款狀態追蹤」。
"""

import base64
import hashlib
import hmac
import json
import uuid

import httpx

BASE = "https://api-pay.line.me/v3/payments"
TIMEOUT = 15.0


def _headers(channel_id, channel_secret, body_json):
    nonce = str(uuid.uuid4())
    string_to_sign = "{}{}{}".format(channel_id, nonce, body_json)
    signature = base64.b64encode(
        hmac.new(channel_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    return {
        "Content-Type": "application/json",
        "X-LINE-ChannelId": str(channel_id),
        "X-LINE-ChannelSecret": channel_secret,
        "X-LINE-Authorization-Nonce": nonce,
        "X-LINE-Authorization": signature,
    }


async def reserve(channel_id, channel_secret, amount, order_id, product_name, confirm_url, cancel_url):
    body = {
        "amount": int(amount),
        "currency": "TWD",
        "orderId": str(order_id),
        "packages": [
            {
                "id": str(order_id),
                "amount": int(amount),
                "products": [{"name": product_name, "quantity": 1, "price": int(amount)}],
            }
        ],
        "redirectUrls": {"confirmUrl": confirm_url, "cancelUrl": cancel_url},
        "options": {"payment": {"capture": True}},
    }
    body_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = _headers(channel_id, channel_secret, body_json)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(BASE + "/request", headers=headers, content=body_json)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    return resp.status_code, data


async def confirm(channel_id, channel_secret, transaction_id, amount):
    body = {"amount": int(amount), "currency": "TWD"}
    body_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = _headers(channel_id, channel_secret, body_json)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            "{}/{}/confirm".format(BASE, transaction_id),
            headers=headers,
            content=body_json,
        )
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    return resp.status_code, data


def verify_webhook(channel_secret, raw_body, signature_header):
    """LINE Pay webhook 簽章驗證（x-line-signature）。"""
    if not signature_header:
        return False
    expected = base64.b64encode(
        hmac.new(channel_secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)