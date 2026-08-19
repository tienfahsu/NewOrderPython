"""商品選項（客製化）的解析、驗證與顯示。"""

import json

MAX_TEXT = 200

ALLOWED_TYPES = ("select", "multi", "text")


def parse_defs(raw):
    """把 products.options（JSON 字串或 dict/list）轉成選項定義清單。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        data = list(raw)
    else:
        try:
            data = json.loads(raw)
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        key = str(d.get("key", "")).strip()
        label = str(d.get("label", "")).strip()
        otype = str(d.get("type", "")).strip()
        if not key or not label or otype not in ALLOWED_TYPES:
            continue
        choices = []
        prices = {}
        if otype != "text":
            raw_choices = d.get("choices") or []
            for c in raw_choices:
                if isinstance(c, dict):
                    s = str(c.get("name", "")).strip()
                    if not s:
                        continue
                    choices.append(s)
                    try:
                        p = int(c.get("price"))
                    except (TypeError, ValueError):
                        p = 0
                    if p > 0:
                        prices[s] = p
                    continue
                s = str(c).strip()
                if s:
                    choices.append(s)
            raw_prices = d.get("prices")
            if isinstance(raw_prices, dict):
                for name, p in raw_prices.items():
                    try:
                        p = int(p)
                    except (TypeError, ValueError):
                        continue
                    if p > 0 and name in choices:
                        prices[name] = p
        item = {"key": key, "label": label, "type": otype}
        if otype != "text":
            item["choices"] = choices
            if prices:
                item["prices"] = prices
        else:
            item["placeholder"] = str(d.get("placeholder", "")).strip()
        out.append(item)
    return out


def dump_defs(defs):
    return json.dumps(defs, ensure_ascii=False)


def parse_item_options(raw):
    """把 order_items.options 的 JSON 字串轉成 {key: value}。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def dump_options(options):
    if not options:
        return ""
    return json.dumps(options, ensure_ascii=False)


def compute_surcharge(defs, selected):
    """依已選選項計算附加金額（加價），未選或無加價為 0。"""
    total = 0
    for d in defs:
        prices = d.get("prices") or {}
        value = selected.get(d["key"])
        if d["type"] == "multi":
            if isinstance(value, list):
                for v in value:
                    total += prices.get(str(v), 0)
        elif value is not None:
            total += prices.get(str(value), 0)
    return total


def sanitize_options(defs, submitted):
    """依商品定義過濾使用者送來的選項，避免塞入任意資料。"""
    if not isinstance(submitted, dict):
        return {}
    result = {}
    for d in defs:
        key = d["key"]
        value = submitted.get(key)
        if d["type"] == "select":
            if value is not None and str(value) in d["choices"]:
                result[key] = str(value)
        elif d["type"] == "multi":
            if isinstance(value, list):
                picked = [str(v) for v in value if str(v) in d["choices"]]
                if picked:
                    result[key] = picked
            elif value is not None and str(value) in d["choices"]:
                result[key] = [str(value)]
        elif d["type"] == "text":
            text = str(value or "").strip()
            if text:
                result[key] = text[:MAX_TEXT]
    return result


def describe(parsed):
    """把已選選項轉成可讀字串，例如：大杯 / 少冰 / 微糖 / 珍珠 / 不要蔥。"""
    parts = []
    for key, value in parsed.items():
        if isinstance(value, list):
            if value:
                parts.append("、".join(str(v) for v in value))
        else:
            s = str(value)
            if s:
                parts.append(s)
    return " / ".join(parts)