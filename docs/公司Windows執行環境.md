# 公司 Windows 機：自動上架執行環境

> 目的：在公司那台 Windows 上把「自動上架」整條線跑起來。照這份由上往下做一次，之後每天只看「每次開工」那節。
> 程式本身跨平台、**不需要改碼**；會卡住的全是環境。

---

## 第零條（先讀）：同一時間只能一台跑

1-1 SKU 表是**品號的唯一正本**，配號本身雖然冪等（同規格沿用舊碼），但**兩台同時跑同一批會撞號**（#S232 實際踩過）。
→ 在 Windows 開工前先確認 Mac 那邊沒有在跑；反之亦然。不要「兩台分工做不同幾支」——名單是同一張。

---

## A. 一次性安裝（六件）

### 1. 三個 repo 要在同一層

`requirements.txt` 用 `-e ../ecommerce-sources` 與 `-e ../ecommerce-media` 裝本機套件，**它們必須是 sibling**：

```
C:\Users\<你>\projects\
├── 1688-to-shopee      ← 本 repo
├── ecommerce-sources   ← 必要（讀表抽屜）
├── ecommerce-media     ← 必要（生圖／vision／尺寸表）
└── cookie-hub          ← 登入用
```

`/start` 會自動 clone 缺的 repo。少一個的症狀是 `pip install` 失敗或 `ModuleNotFoundError: ecommerce_media`。

### 2. `.venv` 與 Playwright

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

⚠️ **Win11 Home 的「智慧型應用程式控制」會擋 PyPI wheel 裡的 `.pyd`**（greenlet、playwright），
症狀是 `DLL load failed` / 「應用程式控制原則已封鎖此檔案」。
解法：**Windows 安全性 → App 與瀏覽器控制 → 智慧型應用程式控制 → 關閉**。
⚠️ 這個動作**不可逆**（要開回只能重灌 Windows）。

### 3. Google Service Account 金鑰

名單、1-1 待貼分頁、上架核對表全部走 `inventory-sync` 這把 SA。把金鑰放到下面**任一處**即可，程式兩處都會掃：

```
%USERPROFILE%\OneDrive\文件\inventory-sync-493112-6047c28ad2b1.json
%USERPROFILE%\.config\gcloud\inventory-sync-493112-6047c28ad2b1.json
```

放在別的地方就在 `.env` 指定：`ORDER_SHEET_SA_JSON=D:\keys\inventory-sync-....json`

> 沒有金鑰的症狀是「⬇️ 更新名單」讀不到——**這不是登入問題**。原本的「🔑 Google 登入」鈕與
> Chrome cookie 收割已於 #S134 退休，現在一律走 SA，Win/Mac 都不必登入 Google。

### 4. `.env`

從 Mac 那台的 `.env` 複製，至少要有：

| 變數 | 什麼時候要 |
|---|---|
| `ANTHROPIC_API_KEY` | **一定要**（標題／詳情文案） |
| `OPENAI_API_KEY` | 只有勾 ✨GPT 生圖、或跑商品資產包的 vision 賣點解析才要 |
| `ASSET_CLOUD_BASE_LADY` / `_BABY` | 只有跑那兩家的資產包同步才要 |

`.env` 不進版控，**必須手動搬**。

### 5. Google Drive Desktop 掛成 `G:`（選配）

只有「商品資產包一鍵同步」（`run_sync_assets_*_windows.bat`）要——它預設寫
`G:\我的雲端硬碟\2. 賣場營運\1.【Nail】\【Nail】1. 商品\商品資產`。
**主上架流程不需要這個。** 路徑不同就用 `ASSET_CLOUD_BASE` 覆蓋。

⚠️ 「商品資產」夾不可搬、「1. 商品」不可改名——程式用本機雲端路徑找它，改了就斷。

### 6. 1688 cookie（**這台最容易卡的一關**）

程式讀的是機器級標準庫：

```
C:\Users\<你>\.joyslu\cookies\1688_nail.json    （Nail）
C:\Users\<你>\.joyslu\cookies\1688_lady.json    （Lady）
C:\Users\<你>\.joyslu\cookies\1688_baby.json    （Baby）
```

⚠️ **Windows 沒有 cookie 收割器**：Mac 靠 cookie-hub 每小時從 Chrome「訂貨-」設定檔收，
Windows 因 Chrome App-Bound 加密讀不到，這條路在這台**不存在**。
而上架 GUI 的「🔑 登入 1688」鈕已於 2026-09-19 拿掉、只剩顯示狀態。

→ **這台要用 1688-order 主視窗登入**：

1. 雙擊 `1688-order\run_windows.bat`
2. 對要用的賣場按 **🔑 登入** → 會開瀏覽器
3. 人工登入該賣場對應的 1688 帳號（Nail＝`jiaorong0826`／Lady＝`joyslunailshop`／Baby＝`luwei03090826`）
4. 看到「✅ 登入成功」＝已寫進標準庫，上架 GUI 就讀得到

（也可以直接跑 `cookie-hub\.venv\Scripts\python guard_gui.py` 開登入警衛室，一個視窗列全部帳號。
cookie-hub 目前只有 `run_guard_mac.command`，Windows 沒有雙擊檔。）

---

## B. 每次開工

1. 確認 Mac 那邊沒在跑（第零條）
2. 雙擊 `run_windows.bat`
3. 選賣場 → **⬇️ 更新名單**（不按就按不動 🚀 開始，這是刻意的硬擋）
4. 看 GUI 上的 1688 登入狀態燈；過期就照 A-6 去登
5. 先勾 1~2 筆試跑 → 確認產出對 → 再全選整批
6. **🚀 開始（缺什麼補什麼）**——抓取 → 文案 → 產出上架檔＋建 1-1＋寫核對表，一次到底
7. **📁 這批的資料夾** 取檔上傳蝦皮（丟進待上架區給人審，不是直接上架）

產出哪一項不滿意，用下排「分步執行」**只換那一樣**：🔄 重抓 1688／✏️ 重生文案／🖼️ 重生圖片／🆕 重建 1-1。
前提是那幾支按過 🚀 開始（沒按過會被擋——防的是「蝦皮有、1-1 沒品號」讓獲利表整片黑）。

---

## C. 只在 Windows 出現的三個雷（#S242）

在這台跑測試**只有 Windows 失敗**時，先懷疑這三類：

1. **cp950 主控台印不出 ✅ 這類符號 → 子程序當掉。**
   例：cookie-hub 登入其實成功，主視窗卻顯示「登入未完成」。
   → 四支 `.bat` 都已內建 `set PYTHONUTF8=1`（會繼承給子程序），**不要拿掉**。
   自己在 CMD 下指令時記得先 `set PYTHONUTF8=1`。
2. **`strftime("%-m/%-d")` 是 macOS/Linux 專屬**，Windows 會拋錯、常被 `except` 吞成空白。
   改用 `f"{d.month}/{d.day}"`。（本 repo 目前掃過沒有這種寫法。）
3. **`with sqlite3.connect()` 只 commit 不關連線** → Windows 鎖檔、暫存檔刪不掉。

---

## D. 驗收：怎麼知道真的通了

三個檢查點，順序不能跳（前一個不過，後面的錯誤訊息會誤導）：

| # | 動作 | 通過的樣子 | 不過代表 |
|---|---|---|---|
| 1 | 開 GUI 按 **⬇️ 更新名單** | 勾選清單長出商品，數量與線上表一致 | SA 金鑰不在／表沒分享給 SA |
| 2 | 勾 1 支**還沒建檔的新品**按 **🚀 開始** | log 有抓取進度、`output\{item_id}.json` 產出且**主圖張數 > 0** | 主圖 0 張＝1688 cookie 過期或被擋 → 回 A-6 |
| 3 | 同一支跑完 | 產出 `上架檔.xlsx`（不是 `上架檔_試跑.xlsx`）、1-1 待貼分頁有品號、核對表長出 MMDD 分頁 | 檔名帶「試跑」＝「🆕 建檔」被取消勾了，**那批在獲利表會整片黑** |

**驗收一律用還沒建檔的新品跑**——不可以刪 1-1 已上架商品重跑（會讓訂貨表死值錯位、重配號讓蝦皮選項貨號對不上獲利表）。

---

<sub>2026-09-21 建。上架規則的正本在 `CLAUDE.md`；本檔只講「在 Windows 這台怎麼把它跑起來」。</sub>
