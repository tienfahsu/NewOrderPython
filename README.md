# 辦公室訂餐 / 下午茶訂購系統

純 Python 開發、部署在 **Cloudflare Workers**（Pyodide 執行環境）的訂餐系統，
搭配 **D1**（Cloudflare 的 SQLite）儲存資料。

功能：
- **廠商與商品管理**：記錄廠商（電話/地址/備註）與其商品（價格/備註/停用）
- **訂單團購**：多組訂單、每人各自點餐、結單後凍結訂購內容
- **多用戶登入**：Email + 密碼（PBKDF2），管理員 / 成員兩種角色
- **收款整合**：
  - 內部收款狀態追蹤（未付款 / 付款中 / 已付款），管理員可標記現金、轉帳等
  - **LINE Pay v3** 線上付款（需 LINE Pay 商家帳號，未設定時自動改用內部追蹤）
- **催款通知**：
  - 系統內通知（所有人都有）
  - **LINE Messaging API** 線上通知（管理員填寫成員綁定後的 LINE User ID）
  - Email 通知（透過 Resend，需 API Key）

## 專案結構

```
src/
  entry.py        # Worker 主入口：路由 + 所有 API handler
  db.py           # D1 存取小幫手與資料表結構
  auth.py         # 密碼雜湊、Session cookie
  money.py        # 應付金額計算、收款看板
  notify.py       # 系統內通知 / LINE Messaging API / Email (Resend)
  linepay.py      # LINE Pay v3 金流（建立付款、確認、webhook）
  static/         # 前端 SPA（原生 HTML/JS/CSS，無建置步驟）
migrations/schema.sql   # D1 資料庫結構（供 wrangler d1 execute 匯入）
tests/smoke_test.py     # 後端冒煙測試（用 sqlite3 mock D1）
```

## 需求

- Node.js + npm（跑 `wrangler`）
- [uv](https://docs.astral.sh/uv/)（跑 `pywrangler`，可選）
- Cloudflare 帳號

## 部署步驟

### 1. 建立 D1 資料庫

```bash
npm install
npx wrangler d1 create team-order-db
# 把回傳的 database_id 填進 wrangler.toml 的 [[d1_databases]] 區塊
```

### 2. 設定密鑰（環境變數）

| 變數 | 必填 | 說明 |
| --- | --- | --- |
| `SESSION_SECRET` | 是 | Session 簽章密鑰，用長隨機字串 |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | 建議 | 首次啟動自動建立系統管理員 |
| `REGISTER_TOKEN` | 否 | 開放註冊的邀請碼；不設則只能由管理員建帳號 |
| `RESEND_API_KEY` / `DEFAULT_FROM_EMAIL` | 否 | 催款 Email（Resend） |
| `LINE_CHANNEL_ACCESS_TOKEN` | 否 | LINE Messaging API 頻道存取權杖（催款 LINE 通知） |
| `LINE_PAY_CHANNEL_ID` / `LINE_PAY_CHANNEL_SECRET` | 否 | LINE Pay 商家金流 |

本機開發：複製 `.dev.vars.example` 為 `.dev.vars` 填入。
正式部署：

```bash
npx wrangler secret put SESSION_SECRET
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put LINE_CHANNEL_ACCESS_TOKEN
npx wrangler secret put LINE_PAY_CHANNEL_SECRET
# 一般變數可寫在 wrangler.toml 的 [vars] 或 Dashboard
```

### 2.5 設定 LINE Messaging API（催款 LINE 通知，選填）

1. 到 [LINE Developers](https://developers.line.biz) 建立 **Messaging API** 頻道
2. 設定環境變數（擇一）：
   - `LINE_CHANNEL_ACCESS_TOKEN`：LINE Developers 後台取得的長期權杖
   - 或 `LINE_CHANNEL_ID` + `LINE_CHANNEL_SECRET`：系統自動用 OAuth 換發權杖
3. 使用者需先加機器人為好友；好友加入後可從「好友管理」或第三方查詢其 **User ID**（U 開頭）
4. 在「帳號管理」把每位成員的 LINE User ID（U 開頭）填入該帳號

另外，「帳號管理」中的 **LINE ID 名稱**（如 `tienfa_hsu`）是**使用者代碼**，與推播用的
User ID 無關：訪客在 QR / 分享頁輸入它即可辨識身分、查詢自己的訂購與金額，不需要 U 開頭。

不設定則催款僅使用系統內通知 + Email。

### 3. 匯入資料庫結構（首次）

```bash
npx wrangler d1 execute team-order-db --remote --file=migrations/schema.sql
```

（Worker 啟動時也會自動 `CREATE TABLE IF NOT EXISTS`，此步驟是為了讓遠端資料庫先就緒。）

### 4. 部署

```bash
npm run deploy   # 等同 npx wrangler deploy
```

完成後即可用 `https://你的名稱.workers.dev` 開站。
第一個註冊的使用者（或 `ADMIN_EMAIL` 指定的帳號）會是管理員。

## 本機執行（不需 Cloudflare / Node）

用 Python 直接跑同一個 Worker，資料存本地 SQLite，可開瀏覽器操作：

```bash
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe httpx
.venv\Scripts\python.exe local_dev.py          # http://127.0.0.1:8787
```

- 預設管理員：`admin@example.com` / `admin12345`
  （會讀取 `.dev.vars` 的 `ADMIN_*`，本機執行時有內建預設值）
- 資料庫存於 `data/team-order.db`，刪掉該檔即可重來
- 金流（LINE Pay）、Email（Resend）實際對外呼叫本機也可使用，
  未設密鑰時系統會自動降級為內部收款追蹤

### 建立測試用範例資料

內建一個 seed 腳本，會建立 3 家廠商、11 項商品、3 筆訂單
（一筆已結單並含收款/催款狀態，一筆進行中，一筆空白）、4 個帳號、通知與催款紀錄：

```bash
.venv\Scripts\python.exe scripts\seed_samples.py --reset   # 重建資料庫並灌入範例資料
```

- 管理員：`admin@example.com` / `admin12345`
- 成員：`chen@example.com`（陳小明，欠款）、`lin@example.com`（林小美，已付款）、
  `zhang@example.com`（張大頭，欠款）— 密碼均為 `pass12345`
- 訂單 #1「週五午餐團」已結單，收款看板可直接測「催款全部未付款」
- 訂單 #2「週三下午茶」進行中，可測點餐
- 訂單 #3 空白，可測空訂單畫面

也可產出 SQL 檔直接灌到遠端 D1：

```bash
.venv\Scripts\python.exe scripts\seed_samples.py --sql migrations\seed_samples.sql
npx wrangler d1 execute team-order-db --remote --file=migrations\seed_samples.sql
```

> 註：要用真實的 Cloudflare workerd 環境開發（`wrangler dev`）需要 64 位元
> Node.js；此專案的 node.exe 為 32 位元，無法安裝 workerd，因此本機模式
> 用 Python 直接模擬 Worker 執行環境，行為與部署版一致。

## 本機開發（workerd）

```bash
npx wrangler dev            # 本機跑 workerd，含本地 D1
# 或
uvx --from workers-py pywrangler dev   # 用 Python 原生的 CLI
```

## 測試

後端冒煙測試（不需 Cloudflare 帳號）：

```bash
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe httpx
.venv\Scripts\python.exe tests\smoke_test.py
```

## 使用流程

1. 管理員建廠商與商品
2. 管理員開「訂單」，設定取餐日期與截止時間
3. 成員在訂單內點餐（可隨時改數量，結單後鎖定）
4. 管理員結單 → 「收款看板」逐人對帳
5. 收款方式：
   - 現場收款：看板按「現金收款 / 轉帳收款」
   - 線上付款：成員或管理員按「LINE Pay 付款連結」，付款後自動回寫
6. 催款：看板按「催款全部未付款」，系統會發系統通知 + LINE + Email，
   並留下催款紀錄

## 安全備註

- 密碼以 PBKDF2-HMAC-SHA256（10 萬次迭代）儲存
- Session 以 HMAC 簽章的 HttpOnly Cookie（SameSite=Lax）
- LINE Pay webhook 有簽章驗證
- 收款看板與帳號管理僅管理員可存取