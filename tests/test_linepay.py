import asyncio
import base64
import hashlib
import hmac
import json
import sys
import types

sys.path.insert(0, "src")


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    @property
    def text(self):
        return json.dumps(self._body)


class FakeClient:
    captured = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, content=None, data=None, json=None):
        FakeClient.captured = {"url": url, "headers": headers, "body": content or data or json}
        return FakeResp(200, {"returnCode": "0000", "returnMessage": "success", "info": {"transactionId": "T1", "paymentUrl": {"web": "https://pay"}}})


httpx_mod = types.ModuleType("httpx")
httpx_mod.AsyncClient = FakeClient
sys.modules["httpx"] = httpx_mod

import linepay

CHANNEL_ID = "12345"
SECRET = "secret-key"


def verify_signature(headers, body):
    string_to_sign = "{}{}{}".format(CHANNEL_ID, headers["X-LINE-Authorization-Nonce"], body)
    expected = base64.b64encode(
        hmac.new(SECRET.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    return expected == headers["X-LINE-Authorization"]


async def main():
    status, data = await linepay.reserve(
        CHANNEL_ID, SECRET, 300, "T1-2", "週五午餐團",
        "http://test.local/api/payments/linepay/callback",
        "http://test.local/#/orders/1",
    )
    cap = FakeClient.captured
    assert cap["url"].endswith("/v3/payments/request"), cap
    assert verify_signature(cap["headers"], cap["body"]), "signature mismatch"
    body = json.loads(cap["body"])
    assert body["amount"] == 300 and body["currency"] == "TWD", body
    assert body["orderId"] == "T1-2", body
    assert body["options"]["payment"]["capture"] is True, body
    assert cap["headers"]["X-LINE-ChannelId"] == CHANNEL_ID, cap["headers"]
    assert status == 200 and data["returnCode"] == "0000", (status, data)

    # confirm
    status, data = await linepay.confirm(CHANNEL_ID, SECRET, "T1", 300)
    cap = FakeClient.captured
    assert cap["url"].endswith("/v3/payments/T1/confirm"), cap
    assert json.loads(cap["body"])["amount"] == 300, cap

    print("LINE Pay signature & payload OK")


asyncio.run(main())