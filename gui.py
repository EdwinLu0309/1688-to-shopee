"""
1688 → 蝦皮 上架小幫手 — GUI 啟動器（仿 1688-order launcher）

一條龍：⬇️ 更新名單 → 勾選商品 → 🚀 開始（缺什麼補什麼）→ 📁 這批的資料夾。

分步執行（Edwin 2026-09-19 定：**只換一樣、其餘沿用上一版**；前提＝那幾支按過 🚀 開始）：
  🔄 重抓 1688   只重抓 1688 資料（不產檔）
  ✏️ 重生文案    重寫標題＋詳情 → 新一版上架檔（圖、品號沿用；1-1／核對表不動）
  🖼️ 重生圖片    用「圖片模板」重生 GPT 圖 → 新一版上架檔（文案、品號沿用）
  🆕 重建 1-1    重寫 _待貼新品＋核對表，上架檔不動（品號跟上一版不同就擋，可選一起換）
  📁 這批的資料夾

1688 登入：cookie 由 cookie-hub 每小時從 Chrome「訂貨-」設定檔收進標準庫，這裡只顯示狀態。
跨平台：GUI 邏輯 Win/Mac 皆可。「更新名單」走 inventory-sync SA 讀 AI 上架名單（該表已分享給 SA）。
"""
import asyncio
import json
import os
import platform
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)
sys.path.insert(0, str(BASE_DIR))

from config.settings import BATCH_DIR, OUTPUT_DIR, RAW_DIR  # noqa: E402
from scraper.shops import SHOPS, get_shop  # noqa: E402

STATE_PATH = BASE_DIR / "config" / "gui_state.json"
DEFAULT_CSV = BASE_DIR / "input" / "lady_ai_list.csv"
ASSETS_DIR = Path(BATCH_DIR)     # 📁 素材夾 → 最新那批的資料夾（見 _on_open_assets）

# 賣場下拉選單顯示名（key → 顯示）
_SHOP_LABELS = {"lady": "Lady 女裝", "nail": "Nail 美甲", "baby": "Baby 母嬰"}

# 1688 登入已不在這裡做：cookie-hub 每小時從 Chrome 收（Edwin 2026-09-19 拿掉登入鈕）
_RELOGIN_HINT = ("1688 的登入可能過期了。\n\n"
                 "到 Chrome 開該賣場的「訂貨-」設定檔登入 1688，"
                 "cookie-hub 一小時內會自動收進來，之後再按一次就好。")


def _cat_names(shop: str) -> dict[str, str]:
    """分類 ID → 顯示文字（從該賣場 profile 的 category_map 反查，先到先得）。"""
    out = {"": "❌無分類"}
    for text, cid in get_shop(shop).category_map.items():
        out.setdefault(cid, text)
    return out

# ── 字體（整體放大，看得清楚）──
F_TITLE = ("Arial", 24, "bold")
F_LBL = ("Arial", 15)
F_LBL_B = ("Arial", 15, "bold")
F_HINT = ("Arial", 12)
F_BTN = ("Arial", 16)
F_BTN_HERO = ("Arial", 20, "bold")
F_BTN_SM = ("Arial", 14)
F_CHK = ("Arial", 14)
F_LOG = ("Menlo", 13)
F_STATUS = ("Arial", 14)


def _open_path(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        messagebox.showwarning("提示", f"路徑不存在：\n{path}")
        return
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", str(path)])
    elif system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)])


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("1688 → 蝦皮 上架小幫手")

        self.BG, self.FG = "#f5f5f5", "#222222"
        try:
            root.tk_setPalette(background=self.BG, foreground=self.FG)
        except Exception:  # noqa: BLE001
            pass
        root.configure(bg=self.BG)

        self.running = False
        self.cancel_event = threading.Event()
        self.shop_var = tk.StringVar(value=self._load_last_shop())
        self.csv_path = tk.StringVar(value=str(self._load_last_csv()))
        self.make_video = tk.BooleanVar(value=True)
        # ⚠️ 建檔**預設開**（Edwin 2026-09-14 改）：正式與預購都住 1-1、都要有品號，
        #    所以「不建檔的產出」不是正常路徑而是試跑。不勾的話 Excel 的 O 商品選項貨號
        #    只能退回「HNV7_美規」這種字串，而獲利表是拿「蝦皮選項貨號＝SKU 品號」去 join
        #    成本與銷量的 → 這批商品的生意在獲利表裡會整片是黑的。
        self.make_staging = tk.BooleanVar(value=True)

        # 文案模板：掃 config/sop/{shop}/*.md，加一份 md 就多一個選項（Edwin 2026-09-14）
        self.sop_var = tk.StringVar(value="（該賣場預設）")
        # 圖片模板：config/design_engine/{shop}/*.md。⚠️ 上游 load_design_spec() 會把資料夾裡
        # 所有 md 串起來當規範 → 不分賣場的話，Nail 勾 GPT 會拿到女裝的「人物比例／模特兒位置」。
        self.img_var = tk.StringVar(value="（尚未建立）")
        self.status_var = tk.StringVar(value="就緒")
        # ⚠️ 「這次開工有沒有按過『⬇️ 更新名單』」——沒按過就不讓按 🚀 一鍵完成（Edwin 2026-09-14 要求）。
        #    本機 CSV 只是線上名單的抄本，不更新就是拿舊抄本去跑，而**線上新增的商品根本不在清單裡**
        #    （踩過：本機停在 2 支、線上其實 48 支）。改時間判斷（超過 N 小時才提醒）會留下
        #    「剛好沒過期但線上剛改過」的縫，所以做成硬性擋住，不做時間判斷。
        self.list_fresh = False

        self.products: list[dict] = []
        self.status: dict[str, dict] = {}
        # 清單欄位（名稱, 最小像素寬）——表頭與每一列共用，grid 才會對齊
        self.COLS = (("選取", 120), ("分類", 96), ("品名", 240),
                     ("抓取", 56), ("文案", 56), ("品號", 56), ("上架檔", 78), ("影片", 56),
                     ("生圖", 72))
        self.check_vars: list[tk.BooleanVar] = []
        self.route_vars: list[tk.BooleanVar] = []   # True = ✨GPT 生圖；False = 🖼 1688 直用
        self.action_buttons: list[tk.Button] = []

        self._build_ui()
        self._refresh_hero()          # 開檔當下就是「沒更新名單」＝灰色鎖住
        self._refresh_csv_state()
        self._refresh_sop_menu()
        self._refresh_img_menu()
        self.root.minsize(760, 860)
        self._refresh_cookie_status()
        self._refresh_products()
        self._center_window()

    # ── 狀態記憶 ──────────────────────────────
    def _shop(self):
        return get_shop(self.shop_var.get())

    def _load_last_shop(self) -> str:
        if STATE_PATH.exists():
            try:
                s = json.loads(STATE_PATH.read_text(encoding="utf-8")).get("shop", "")
                if s in SHOPS:
                    return s
            except Exception:  # noqa: BLE001
                pass
        return "lady"

    def _load_last_csv(self) -> Path:
        if STATE_PATH.exists():
            try:
                p = json.loads(STATE_PATH.read_text(encoding="utf-8")).get("csv_path", "")
                if p and Path(p).exists():
                    return Path(p)
            except Exception:  # noqa: BLE001
                pass
        return self._shop().csv_path if self.shop_var.get() != "lady" else DEFAULT_CSV

    def _save_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            STATE_PATH.write_text(
                json.dumps({"csv_path": self.csv_path.get(), "shop": self.shop_var.get()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _on_shop_change(self, *_):
        """切賣場：名單路徑換成該賣場預設、重載清單、更新 cookie 狀態。"""
        sp = self._shop()
        # lady 舊檔名向後相容：存在就用舊的 lady_ai_list.csv
        self.csv_path.set(str(DEFAULT_CSV if (sp.key == "lady" and DEFAULT_CSV.exists())
                              else sp.csv_path))
        self._save_state()
        self.list_fresh = False          # 換賣場＝換一份名單，要重抓
        self._refresh_csv_state()
        self._refresh_sop_menu()
        self._refresh_img_menu()
        self._refresh_hero()
        self._refresh_cookie_status()
        self._refresh_products()

    # ── UI ──────────────────────────────
    def _build_ui(self) -> None:
        BG, FG = self.BG, self.FG

        tk.Label(self.root, text="1688 → 蝦皮 上架小幫手",
                 font=F_TITLE, pady=10, bg=BG, fg=FG).pack()

        # ── 賣場選擇 ──
        shop_frame = tk.Frame(self.root, padx=24, pady=4, bg=BG)
        shop_frame.pack(fill="x")
        tk.Label(shop_frame, text="⓪ 賣場：", font=F_LBL_B, bg=BG, fg=FG).pack(side="left")
        self._shop_label_var = tk.StringVar(value=_SHOP_LABELS[self.shop_var.get()])
        shop_menu = tk.OptionMenu(shop_frame, self._shop_label_var, *_SHOP_LABELS.values(),
                                  command=self._on_shop_pick)
        shop_menu.config(font=F_BTN_SM)
        shop_menu.pack(side="left", padx=4)

        # ── 名單 + 更新 ──
        csv_frame = tk.Frame(self.root, padx=24, pady=4, bg=BG)
        csv_frame.pack(fill="x")
        tk.Label(csv_frame, text="① 名單：", font=F_LBL_B, bg=BG, fg=FG).pack(side="left")
        # 名單由賣場決定（input/{shop}_ai_list.csv），沒有讓人挑檔的必要 → 只顯示狀態。
        # 要加新賣場是改 code 的事（.env 設名單 ID ＋ shops.py 的 profile），不是在這裡選檔。
        self.csv_state = tk.StringVar(value="")
        tk.Label(csv_frame, textvariable=self.csv_state, font=F_LBL,
                 bg=BG, fg="#1a7f37").pack(side="left", padx=6)
        self.fetch_btn = tk.Button(csv_frame, text="⬇️ 更新名單", font=F_BTN,
                                   command=self._on_fetch_list)
        self.fetch_btn.pack(side="left")
        self.action_buttons.append(self.fetch_btn)
        tk.Label(self.root, text="（每次開工先按這顆：程式跑的是本機抄本，不更新就看不到你線上新增的商品）",
                 font=F_HINT, fg="#888", bg=BG).pack(anchor="w", padx=24)

        # ── 商品勾選清單 ──
        list_lbl = tk.Frame(self.root, padx=24, pady=6, bg=BG)
        list_lbl.pack(fill="x")
        tk.Label(list_lbl, text="② 勾要做的商品（右側 ✨GPT＝這支自己生圖，不勾＝直接用 1688 的圖）：",
                 font=F_LBL_B, bg=BG, fg=FG).pack(side="left")
        self.count_var = tk.StringVar(value="尚未載入名單")
        tk.Label(list_lbl, textvariable=self.count_var, font=F_LBL, bg=BG, fg="#1a7f37").pack(side="left", padx=8)
        tk.Button(list_lbl, text="全不選", font=F_BTN_SM,
                  command=lambda: self._set_all_checks(False)).pack(side="right", padx=3)
        tk.Button(list_lbl, text="全選", font=F_BTN_SM,
                  command=lambda: self._set_all_checks(True)).pack(side="right", padx=3)

        # ⚠️ 表頭在捲動區外、資料列在捲動區內，兩個容器寬度不同 → 用「各排各的」一定對不齊
        #    （2026-09-15 跑版）。改成**兩邊套同一份欄寬定義並用 grid**，欄位由格線決定位置。
        hdr = tk.Frame(self.root, padx=24, bg=BG)
        hdr.pack(fill="x")
        for i, (name, w) in enumerate(self.COLS):
            hdr.grid_columnconfigure(i, minsize=w, weight=(1 if name == "品名" else 0))
            tk.Label(hdr, text=("" if name in ("選取",) else name), anchor=("w" if i <= 2 else "center"),
                     font=F_HINT, bg=BG, fg="#888").grid(row=0, column=i, sticky="ew")
        # 最右邊補一格＝捲軸＋畫布邊框的寬度。寫死會差幾個 px（實測 7），所以開窗後量實際值再補。
        self._hdr = hdr
        hdr.grid_columnconfigure(len(self.COLS), minsize=18)

        list_outer = tk.Frame(self.root, padx=24, bg=BG)
        list_outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(list_outer, height=210, bg="#ffffff",
                                highlightthickness=1, highlightbackground="#ccc")
        scroll = tk.Scrollbar(list_outer, orient="vertical", command=self.canvas.yview)
        self.checks_frame = tk.Frame(self.canvas, bg="#ffffff")
        self.checks_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._checks_win = self.canvas.create_window((0, 0), window=self.checks_frame, anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._checks_win, width=e.width))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._scrollbar = scroll
        self.root.after(200, self._sync_header_gutter)
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 3)), "units"))

        # ── 一鍵完成（主按鈕）──
        # macOS 的 tk.Button 會忽略 bg（用原生白按鈕），故改用 Frame+Label 自己上色，
        # Label 的 bg 在 mac 才會真的渲染 → 綠底白字看得到。
        # ── 產出選項（放在「一鍵完成」之前：先設定再執行才合邏輯，Edwin 2026-09-14）──
        sop_frame = tk.Frame(self.root, padx=24, pady=2, bg=BG)
        sop_frame.pack(fill="x")
        tk.Label(sop_frame, text="文案模板：", font=F_LBL_B, bg=BG, fg=FG).pack(side="left")
        self.sop_menu = tk.OptionMenu(sop_frame, self.sop_var, "（該賣場預設）")
        self.sop_menu.config(font=F_BTN_SM)
        self.sop_menu.pack(side="left")
        tk.Label(sop_frame, text="（決定標題與詳情怎麼寫）",
                 font=F_HINT, fg="#888", bg=BG).pack(side="left", padx=(4, 18))
        tk.Label(sop_frame, text="圖片模板：", font=F_LBL_B, bg=BG, fg=FG).pack(side="left")
        self.img_menu = tk.OptionMenu(sop_frame, self.img_var, "（尚未建立）")
        self.img_menu.config(font=F_BTN_SM)
        self.img_menu.pack(side="left")
        self.img_hint = tk.StringVar(value="")
        tk.Label(sop_frame, textvariable=self.img_hint,
                 font=F_HINT, fg="#888", bg=BG).pack(side="left", padx=4)

        tk.Checkbutton(self.root, text="🎬 合成短影片（選配：不勾就不做，也不算「缺」；蝦皮 Excel 沒有影片欄，要在後台手動補）",
                       variable=self.make_video,
                       font=F_HINT, bg=BG, fg=FG, selectcolor="#ffffff",
                       activebackground=BG).pack(anchor="w", padx=24, pady=(2, 0))

        hero = tk.Frame(self.root, padx=24, pady=8, bg=BG)
        hero.pack(fill="x")
        self.hero_bg = tk.Frame(hero, bg="#1a7f37", height=60, cursor="hand2")
        self.hero_bg.pack(fill="x")
        self.hero_bg.pack_propagate(False)
        self.run_all_lbl = tk.Label(self.hero_bg, text="🚀 一鍵完成（抓取 → 產出上架檔）",
                                    font=F_BTN_HERO, bg="#1a7f37", fg="#ffffff", cursor="hand2")
        self.run_all_lbl.place(relx=0.5, rely=0.5, anchor="center")
        for w in (self.hero_bg, self.run_all_lbl):
            w.bind("<Button-1>", lambda e: (None if self.running else self._on_run_all()))
        tk.Label(self.root,
                 text="③ 產出會存成 batch/{賣場}/{日期}/文案_v1、v2…　舊版一律保留，不滿意就重跑一版再挑",
                 font=F_HINT, fg="#888", bg=BG).pack(anchor="w", padx=24)

        # ── 分步 / 其他 ──
        tk.Label(self.root, text="分步執行（只換一樣、其餘沿用上一版；要先按過 🚀 開始）：", font=F_HINT, fg="#666",
                 bg=BG).pack(anchor="w", padx=24, pady=(4, 0))
        steps = tk.Frame(self.root, padx=24, pady=2, bg=BG)
        steps.pack(fill="x")

        def step_btn(text, cmd):
            b = tk.Button(steps, text=text, font=F_BTN_SM, command=cmd)
            b.pack(side="left", padx=(0, 6))
            self.action_buttons.append(b)
            return b

        # 下半段＝**只重做某一項**。上半段已經「缺什麼補什麼」，所以這裡每顆都是覆寫性的例外動作，
        # 點了才會發生（Edwin 2026-09-15：兩段分開，第一段湊齊、第二段挑不滿意的重做）。
        step_btn("🔄 重抓 1688", self._on_scrape)
        step_btn("✏️ 重生文案", self._on_regen_copy)
        step_btn("🖼️ 重生圖片", self._on_regen_images)
        step_btn("🆕 重建 1-1", self._on_rebuild_staging)
        step_btn("📁 這批的資料夾", self._on_open_assets)

        # cookie 狀態
        cf = tk.Frame(self.root, padx=24, pady=4, bg=BG)
        cf.pack(fill="x")
        tk.Label(cf, text="1688 登入：", font=F_LBL, bg=BG, fg=FG).pack(side="left")
        self.cookie_status = tk.Label(cf, text="", font=F_LBL_B, bg=BG)
        self.cookie_status.pack(side="left")

        # 日誌
        lf = tk.Frame(self.root, padx=24, bg=BG)
        lf.pack(fill="both", expand=True)
        self.log_text = tk.Text(lf, height=7, font=F_LOG, wrap="word", relief="solid",
                                borderwidth=1, bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="#d4d4d4", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        # 底部
        bottom = tk.Frame(self.root, padx=24, pady=8, bg=BG)
        bottom.pack(fill="x")
        # ⏹ 停止：只在跑的時候才出現（閒著時是一顆永遠灰的按鈕＝純噪音）。
        # 功能本身要留——一輪 26 支要跑很久，中途發現勾錯了得停得下來。
        self.stop_btn = tk.Button(bottom, text="⏹ 停止", font=F_BTN_SM, width=8,
                                  command=self._on_stop)
        self._stop_parent = bottom
        tk.Label(bottom, textvariable=self.status_var, font=F_STATUS, fg="#555", bg=BG,
                 wraplength=560, justify="left", anchor="w").pack(side="left", fill="x", expand=True)
        tk.Frame(self.root, height=8, bg=BG).pack()

    def _on_shop_pick(self, label: str) -> None:
        """OptionMenu 顯示的是中文標籤 → 轉回 shop key 再套用。"""
        key = next((k for k, v in _SHOP_LABELS.items() if v == label), "lady")
        self.shop_var.set(key)
        self._on_shop_change()

    def _center_window(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max(0, (self.root.winfo_screenheight() - h) // 2)
        self.root.geometry(f"+{x}+{y}")

    # ── 商品勾選清單 ──────────────────────────────
    def _refresh_products(self) -> None:
        for w in self.checks_frame.winfo_children():
            w.destroy()
        self.products, self.check_vars, self.route_vars = [], [], []

        csv = Path(self.csv_path.get())
        if not csv.exists():
            self.count_var.set("尚未載入名單（按「⬇️ 更新名單」）")
            return
        try:
            from scraper.ai_list_reader import parse_ai_list_csv
            self.products = parse_ai_list_csv(csv, shop=self.shop_var.get())
        except Exception as e:  # noqa: BLE001
            self.count_var.set(f"名單解析失敗：{e}")
            return

        cat_names = _cat_names(self.shop_var.get())
        # 版面＝表格（Edwin 2026-09-15：「東西都擠在一起、前後數據不對齊」）：
        # 左半是可變長度的商品資訊、右半是固定寬度的狀態欄，逐列對得整整齊齊。
        for i, (name, w) in enumerate(self.COLS):
            self.checks_frame.grid_columnconfigure(i, minsize=w, weight=(1 if name == "品名" else 0))
        for r, p in enumerate(self.products):
            sel_var = tk.BooleanVar(value=False)
            gpt_var = tk.BooleanVar(value=False)
            self.check_vars.append(sel_var)
            self.route_vars.append(gpt_var)
            cat = cat_names.get(p.get("category", ""), p.get("category", ""))
            warn = "" if p.get("category") else " ⚠️"
            st = self.status.get(p["code"]) or {}

            tk.Checkbutton(self.checks_frame, text=p["code"], variable=sel_var, anchor="w",
                           font=F_CHK, bg="#ffffff", fg="#111111", selectcolor="#ffffff",
                           activebackground="#f0f0f0", command=self._update_count,
                           padx=2, pady=2).grid(row=r, column=0, sticky="w")
            tk.Label(self.checks_frame, text=f"[{cat}{warn}]", anchor="w", font=F_CHK,
                     bg="#ffffff", fg="#666666").grid(row=r, column=1, sticky="w")
            tk.Label(self.checks_frame, text=p.get("name", "")[:18], anchor="w", font=F_CHK,
                     bg="#ffffff", fg="#111111").grid(row=r, column=2, sticky="w")
            for ci, key in enumerate(("抓取", "文案", "品號", "上架檔", "影片"), start=3):
                v = st.get(key)
                if key == "上架檔":
                    txt = f"{v[4:6]}/{v[6:8]}" if v and len(str(v)) == 8 else "—"
                    fg = "#1a7f37" if v else "#bbbbbb"
                else:
                    txt = "✓" if v else ("—" if v is False else "?")
                    fg = "#1a7f37" if v else ("#cc7a00" if v is None else "#bbbbbb")
                tk.Label(self.checks_frame, text=txt, anchor="center", font=F_CHK,
                         bg="#ffffff", fg=fg).grid(row=r, column=ci, sticky="ew")
            tk.Checkbutton(self.checks_frame, text="✨GPT", variable=gpt_var, font=("Arial", 12),
                           bg="#ffffff", fg="#7a3ea8", selectcolor="#ffffff",
                           activebackground="#f0f0f0",
                           command=self._update_count).grid(row=r, column=8, sticky="w")
        self._update_count()

    # ── 每支商品「做到哪了」──────────────────────────────
    #
    # ⚠️ **刻意不另存一份狀態檔**（Edwin 2026-09-15 問「是不是該有內部表格記誰做過」）：
    #    狀態檔會跟現實脫節——檔案被刪了它還說做過，或反過來，而那種 bug 最難查。
    #    每一步的「做過沒」都從**真實產物**讀：raw json／文案快取／1-1 SKU表／批次夾／影片檔。
    #    manifest.json 只記歷史（哪天哪一版用什麼模板），不負責判斷狀態——兩者分開才不會互相汙染。
    def _scan_status(self) -> None:
        """掃一次：每支商品的 抓取／文案／品號／上架檔／影片 各自做了沒。

        1-1 要打 API，所以只在「更新名單」與切賣場時掃，不是每次重畫都掃。
        """
        self.status: dict[str, dict] = {}
        tpl_tag = ""
        try:
            from scraper.batch_pipeline2 import _template_tag
            tpl_tag = _template_tag(self._sop_override())
        except Exception:  # noqa: BLE001
            pass
        # 1-1：哪些商品編號已經有 SKU 品號（唯一正本）
        coded: set[str] = set()
        try:
            from scraper.master_staging import load_master_context
            ctx = load_master_context(self.shop_var.get())
            for r in ctx.sku_rows:
                if len(r) >= 2 and r[0].strip() and r[1].strip():
                    coded.add(r[1].split("_")[0].strip())
        except Exception as e:  # noqa: BLE001
            self._log(f"⚠️ 讀 1-1 失敗，品號狀態這欄先留空：{e}")
            coded = None
        done = self._done_map()
        from scraper.batch_pipeline2 import ai_cache_path, cache_is_fresh
        from scraper.playwright_scraper import raw_is_fresh
        from scraper.shops import get_shop
        sp = get_shop(self.shop_var.get())
        for p in self.products:
            item, code = str(p.get("item_id")), p.get("code", "")
            rd = Path(RAW_DIR) / item
            self.status[code] = {
                # 抓取／文案都要「是現行版本」才算做過（舊版＝缺，開始時自動補）
                "抓取": raw_is_fresh(Path(RAW_DIR) / f"{item}.json"),
                "文案": cache_is_fresh(ai_cache_path(p, tpl_tag), sp),
                "品號": (code in coded) if coded is not None else None,
                "上架檔": done.get(item),          # 有值＝哪天產過
                "影片": (rd / "video" / f"{code}.mp4").exists(),
            }

    def _sync_header_gutter(self) -> None:
        """對齊表頭與資料列的右半欄。

        ⚠️ 算不準：捲軸寬、畫布邊框、平台邊距加起來實測差 7px，寫死在不同機器上還是會歪。
        所以**量了再校**——比對同一欄在表頭與第一列的實際 x，差多少就把最右邊那格補多少。
        """
        try:
            rows = self.checks_frame.grid_slaves(row=0)
            if not rows:
                return
            col = 3          # 第一個狀態欄，右半段的起點
            hx = next((w.winfo_rootx() for w in self._hdr.grid_slaves()
                       if w.grid_info()["column"] == col), None)
            rx = next((w.winfo_rootx() for w in rows if w.grid_info()["column"] == col), None)
            if hx is None or rx is None:
                return
            now = int(self._hdr.grid_columnconfigure(len(self.COLS))["minsize"])
            self._hdr.grid_columnconfigure(len(self.COLS), minsize=max(0, now + (hx - rx)))
            self._hdr.update_idletasks()
        except Exception:  # noqa: BLE001
            pass

    def _rescan_and_redraw(self) -> None:
        self._status("掃描每支商品做到哪了…")
        self._scan_status()
        self._refresh_products()
        self.root.after(50, self._sync_header_gutter)
        self._status("就緒")

    def _badges(self, code: str) -> str:
        """一行狀態徽章，缺什麼一眼看得出來。"""
        st = self.status.get(code)
        if not st:
            return ""
        def m(ok):
            return "✓" if ok else ("—" if ok is False else "?")
        d = st["上架檔"]
        excel = f"上架檔 {d[4:6]}/{d[6:8]}" if d and len(d) == 8 else "上架檔 —"
        return f"抓{m(st['抓取'])} 文案{m(st['文案'])} 品號{m(st['品號'])} {excel} 影片{m(st['影片'])}"

    def _done_map(self) -> dict[str, str]:
        """item_id → 最近一次產出的日期（掃 batch/{shop}/*/manifest.json）。

        Edwin 2026-09-14：「已經有產出的商品要不要備註」——名單上的舊商品和新商品長得
        一模一樣，誤勾就會重跑一支已經上架的。這個對照讓清單直接標出來。
        ⚠️ key 用 item_id 不用編號：同一個編號會有多個款式／多次改版，item_id 才是 1688 那一支。
        """
        out: dict[str, str] = {}
        base = Path(BATCH_DIR) / self.shop_var.get()
        if not base.exists():
            return out
        # manifest 在 batch/{shop}/{日期}/文案_vN/manifest.json；舊批次（版本化之前）在日期夾底下
        for mf in sorted(list(base.glob("*/*/manifest.json")) + list(base.glob("*/manifest.json"))):
            day = mf.parent.name if mf.parent.name.isdigit() else mf.parent.parent.name
            try:
                doc = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for it in doc.get("商品", []):
                if it.get("item_id"):
                    out[str(it["item_id"])] = day      # 後面的批次覆蓋前面 → 留最近一次
        return out

    def _set_all_checks(self, val: bool) -> None:
        for v in self.check_vars:
            v.set(val)
        self._update_count()

    def _update_count(self) -> None:
        sel = sum(1 for v in self.check_vars if v.get())
        gpt = sum(1 for sv, gv in zip(self.check_vars, self.route_vars) if sv.get() and gv.get())
        extra = f"（其中 {gpt} 支走 ✨GPT）" if gpt else ""
        self.count_var.set(f"名單 {len(self.products)} 筆，已勾 {sel} 筆{extra}")

    def _selected(self) -> list[dict]:
        out = []
        for p, sv, gv in zip(self.products, self.check_vars, self.route_vars):
            if sv.get():
                q = dict(p)
                q["route"] = "gpt" if gv.get() else "1688"
                out.append(q)
        return out

    # ── 共用 helpers ──────────────────────────────
    def _log(self, msg: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _thread_log(self, msg: str) -> None:
        self.root.after(0, self._log, msg)
        self.root.after(0, self._status, msg)

    def _set_buttons(self, state: str) -> None:
        for b in self.action_buttons:
            b.config(state=state)

    def _refresh_cookie_status(self) -> None:
        cookie = self._shop().cookie_path
        if cookie.exists():
            try:
                n = len(json.loads(cookie.read_text(encoding="utf-8")))
                self.cookie_status.config(
                    text=f"✅ {_SHOP_LABELS[self.shop_var.get()]} 已登入（{n} 筆）", fg="#1a7f37")
            except Exception:  # noqa: BLE001
                self.cookie_status.config(text="⚠️ cookie 檔壞了", fg="#cf222e")
        else:
            self.cookie_status.config(
                text=f"❌ {_SHOP_LABELS[self.shop_var.get()]} 未登入（到 Chrome「訂貨-」設定檔登入 1688，一小時內自動收）",
                fg="#cf222e")

    def _refresh_sop_menu(self) -> None:
        """依目前賣場重建文案模板下拉（掃 config/sop/{shop}/*.md）。"""
        from scraper.shops import get_shop
        names = ["（該賣場預設）"] + [p.stem for p in get_shop(self.shop_var.get()).copy_templates()]
        menu = self.sop_menu["menu"]
        menu.delete(0, "end")
        for n in names:
            menu.add_command(label=n, command=lambda v=n: self.sop_var.set(v))
        if self.sop_var.get() not in names:
            self.sop_var.set(names[0])

    def _refresh_img_menu(self) -> None:
        """依賣場重建圖片模板下拉（掃 config/design_engine/{shop}/*.md；丟一份 md 就多一個選項）。"""
        from scraper.image_templates import list_templates
        names = [p.stem for p in list_templates(self.shop_var.get())]
        menu = self.img_menu["menu"]
        menu.delete(0, "end")
        for n in (names or ["（尚未建立）"]):
            menu.add_command(label=n, command=lambda v=n: (self.img_var.set(v), self._refresh_img_hint()))
        if self.img_var.get() not in (names or ["（尚未建立）"]):
            self.img_var.set((names or ["（尚未建立）"])[0])
        self._refresh_img_hint()

    def _refresh_img_hint(self) -> None:
        t = self._img_template_obj()
        self.img_hint.set(f"（{t.label}；🚀 開始只用在勾 ✨GPT 的商品，🖼️ 重生圖片也用它）" if t
                          else "（這個賣場還沒有圖片模板）")

    def _img_template(self) -> str | None:
        v = self.img_var.get()
        return None if v.startswith("（") else v

    def _img_template_obj(self):
        name = self._img_template()
        if not name:
            return None
        from scraper.image_templates import load_template
        try:
            return load_template(self.shop_var.get(), name)
        except Exception:  # noqa: BLE001
            return None

    def _sop_override(self) -> list[str] | None:
        """下拉選的模板 → sop_texts 用的相對路徑；選預設回 None。"""
        v = self.sop_var.get()
        if v.startswith("（"):
            return None
        from config.settings import BASE_DIR
        from scraper.shops import get_shop
        base = Path(BASE_DIR) / "config" / "sop"
        for p in get_shop(self.shop_var.get()).copy_templates():
            if p.stem == v:
                return [str(p.relative_to(base))]     # sop_texts 吃的是相對 config/sop 的路徑
        return None

    def _mark_list_fresh(self) -> None:
        self.list_fresh = True
        self._refresh_csv_state()
        self._refresh_hero()

    def _refresh_csv_state(self) -> None:
        """名單那行顯示什麼：檔名＋抓取時間，沒更新就講「請先按更新名單」。"""
        f = Path(self.csv_path.get())
        if not self.list_fresh:
            self.csv_state.set(f"{f.name}　← 還沒更新，請先按右邊那顆")
        else:
            ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%m/%d %H:%M") if f.exists() else "?"
            self.csv_state.set(f"{f.name}　{ts} 更新")

    def _refresh_hero(self) -> None:
        """一鍵按鈕的外觀：忙碌 or 名單沒更新 → 灰色＋說明文字。"""
        blocked = self.running or not self.list_fresh
        color = "#9aa0a6" if blocked else "#1a7f37"
        self.hero_bg.config(bg=color)
        self.run_all_lbl.config(
            bg=color,
            text=("🚀 開始（缺什麼補什麼）" if self.list_fresh
                  else "🔒 請先按「⬇️ 更新名單」"))

    def _busy(self, on: bool, cancellable: bool = False) -> None:
        self.running = on
        self._set_buttons("disabled" if on else "normal")
        if on and cancellable:
            self.stop_btn.pack(side="right")
        else:
            self.stop_btn.pack_forget()
        self._refresh_hero()

    def _guard(self) -> bool:
        if self.running:
            messagebox.showwarning("提示", "有任務正在執行中，請等待完成")
            return False
        return True

    def _guard_selection(self) -> list[dict] | None:
        if not self.products:
            messagebox.showwarning("提示", "還沒載入名單，請先按「⬇️ 更新名單」")
            return None
        sel = self._selected()
        if not sel:
            messagebox.showwarning("提示", "請先在清單勾選要處理的商品（可先勾 1-2 筆試跑）")
            return None
        return sel

    def _warn_no_category(self, sel: list[dict]) -> bool:
        nocat = [p["code"] for p in sel if not p.get("category")]
        if nocat:
            return messagebox.askyesno(
                "有商品無分類",
                f"這些勾選商品沒有分類 ID（上傳蝦皮會被擋）：\n{', '.join(nocat)}\n\n要繼續嗎？")
        return True

    def _block_missing_stock(self, sel: list[dict]) -> bool:
        """現貨沒填安全存量 → 擋下並列出編號（Edwin 2026-09-16：請去名單填好再重建）。"""
        from scraper.ai_list_reader import missing_safety_stock, missing_stock_message
        miss = missing_safety_stock(sel)
        if miss:
            messagebox.showerror("安全存量沒填", missing_stock_message(miss))
            return False
        return True

    def _warn_gpt(self, sel: list[dict]) -> bool:
        """🚀 開始時勾了 ✨GPT 的商品：還沒生過的才會生（生過的沿用），先講清楚要花多少。"""
        gpt = [p for p in sel if p.get("route") == "gpt"]
        if not gpt:
            return True
        # ⚠️ 沒有該賣場的圖片模板就**擋下來**，不要拿別家的規範生圖（女裝的「人物比例／
        #    模特兒位置」套在集塵器上會生出很怪的圖）
        tpl = self._img_template_obj()
        if tpl is None:
            messagebox.showerror(
                "還沒有圖片模板",
                f"{_SHOP_LABELS[self.shop_var.get()]} 還沒有圖片模板，"
                f"這 {len(gpt)} 支不能走 GPT 生圖。\n\n"
                f"模板要放在 config/design_engine/{self.shop_var.get()}/ 底下（.md）。\n"
                "先取消那幾支的 ✨GPT，或請 Claude 起草一份模板。")
            return False
        from scraper.image_templates import PRICE_PER_IMAGE, latest_set
        new = [p for p in gpt if not latest_set(Path(RAW_DIR) / str(p["item_id"]))]
        if not new:
            return True                     # 全都生過了 → 沿用，不花錢
        n_img = len(new) * tpl.count
        cost = n_img * PRICE_PER_IMAGE
        return messagebox.askyesno(
            "✨ GPT 生圖確認",
            f"這 {len(new)} 支要用 GPT 生圖：{', '.join(p['code'] for p in new)}\n"
            + (f"（另 {len(gpt) - len(new)} 支之前生過，沿用不重生）\n" if len(gpt) > len(new) else "")
            + f"\n模板：{tpl.name}（每支 {tpl.label}）\n"
            f"費用：{n_img} 張，約 US${cost:.2f}（台幣 {cost * 32:.0f} 元）＋比較慢，圖會上傳圖床\n\n"
            "要繼續嗎？")

    def _staging_precheck(self) -> tuple[bool, bool] | None:
        """回 (make_staging, staging_force)；None＝使用者取消執行。

        開跑前在主執行緒就把「上一批還沒貼走」的對話框處理掉，
        背景執行緒不跳 UI。預檢連線失敗就照常跑（write_staging 端還有同一道防線）。
        """
        if not self.make_staging.get():
            if not messagebox.askyesno(
                "沒有建檔＝這份檔不能拿去上架",
                "「🆕 建檔」沒有勾。\n\n"
                "不建檔就配不到 SKU 品號，Excel 的「商品選項貨號」只能填「HNV7_美規」這種字串。\n"
                "獲利表是靠『蝦皮選項貨號＝SKU 品號』去對成本與銷量的——\n"
                "**這批商品上架後，在獲利表裡會整片是黑的，而且沒有任何錯誤訊息。**\n\n"
                "確定只是試跑嗎？（產出的檔名會標成「上架檔_試跑.xlsx」提醒你別傳）"):
                return None
            return (False, False)
        shop = self.shop_var.get()
        try:
            from scraper.master_staging import staging_has_leftover
            leftover = staging_has_leftover(shop)
        except Exception as e:  # noqa: BLE001
            self._log(f"⚠️ 待貼分頁預檢失敗（{e}），照常執行")
            return (True, False)
        if leftover:
            if not messagebox.askyesno(
                "待貼分頁還有上一批",
                "1-1「_待貼新品」還留著上一批沒貼走的資料。\n\n"
                "要覆蓋嗎？（選「否」取消執行；先把上一批貼進商品表/SKU表再跑）"):
                return None
            return (True, True)
        return (True, False)

    # ── ⬇️ 更新名單（走 Service Account 讀私有表；#S134 不再需要 Google 登入）──
    def _on_fetch_list(self) -> None:
        if not self._guard():
            return
        self._busy(True)
        self._log("用 Service Account 抓最新 AI 上架名單…")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self) -> None:
        try:
            from scraper.sheet_fetcher import fetch_ai_list
            out = Path(self.csv_path.get()) if self.csv_path.get() else None
            res = fetch_ai_list(out_path=out, shop=self.shop_var.get())
            if res.get("ok"):
                self._thread_log(f"✅ 名單已更新（來源 {res['profile']}，{res['bytes']} bytes）")
                self.root.after(0, self._mark_list_fresh)
                self.root.after(0, self._refresh_products)
                self.root.after(0, self._rescan_and_redraw)
            else:
                self._thread_log(f"❌ 抓取失敗：{res.get('error')}")
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._thread_log(f"更新名單錯誤：{e}")
        finally:
            self.root.after(0, self._on_task_done)
            self.root.after(0, self._on_task_done)

    # ── 🚀 一鍵完成 ──────────────────────────────
    def _plan(self, sel: list[dict]) -> dict:
        """這次實際會做什麼——由「每支缺什麼」算出來，不是由勾選猜出來。

        Edwin 2026-09-15：「我連跟你溝通了幾回都還是沒有很確定現在會出現什麼」。
        所以動作不再是一堆帶但書的勾選，而是**把缺的補上**，並在按下去之前把清單列給他看。
        """
        need_scrape, need_copy, need_code, need_video = [], [], [], []
        for p in sel:
            st = self.status.get(p["code"]) or {}
            if not st.get("抓取"):
                need_scrape.append(p)
            if not st.get("文案"):
                need_copy.append(p)
            if st.get("品號") is False:
                need_code.append(p)
            if self.make_video.get() and not st.get("影片"):
                need_video.append(p)
        return {"抓取": need_scrape, "文案": need_copy, "品號": need_code,
                "影片": need_video, "全部": sel}

    def _plan_text(self, plan: dict) -> str:
        n = lambda k: len(plan[k])  # noqa: E731
        sel = len(plan["全部"])
        lines = [f"這次處理 {sel} 支商品：", ""]
        lines.append(f"　抓 1688　　{n('抓取')} 支" + (f"（其餘 {sel - n('抓取')} 支用既有資料）" if n('抓取') < sel else ""))
        lines.append(f"　文案　　　{n('文案')} 支重生" + (f"（其餘 {sel - n('文案')} 支用既有文案）" if n('文案') < sel else "")
                     + f"　模板：{self.sop_var.get()}")
        lines.append(f"　SKU 品號　{n('品號')} 支要配號"
                     + (f"（其餘 {sel - n('品號')} 支 1-1 已經有了，沿用）" if n('品號') < sel else "")
                     + "，並寫進 1-1「_待貼新品」")
        lines.append(f"　上架檔　　{sel} 支 → 新的一版（舊版保留）")
        gpt = [p for p in plan["全部"] if p.get("route") == "gpt"]
        if gpt:
            from scraper.image_templates import PRICE_PER_IMAGE, latest_set
            t = self._img_template_obj()
            new = [p for p in gpt if not latest_set(Path(RAW_DIR) / str(p["item_id"]))]
            cost = len(new) * (t.count if t else 1) * PRICE_PER_IMAGE
            lines.append(f"　✨GPT 生圖　{len(new)} 支要生（每支 {t.label if t else '?'}）"
                         + (f"、{len(gpt) - len(new)} 支沿用之前生的" if len(gpt) > len(new) else "")
                         + f"　模板：{self.img_var.get()}　約 US${cost:.2f}（台幣 {cost * 32:.0f} 元）")
        if self.make_video.get():
            lines.append(f"　影片　　　{n('影片')} 支要合成" + (f"（其餘 {sel - n('影片')} 支已有）" if n('影片') < sel else ""))
        else:
            lines.append("　影片　　　不做（沒勾「合成短影片」）")
        return "\n".join(lines)

    def _on_run_all(self) -> None:
        if not self.list_fresh:
            messagebox.showwarning(
                "請先更新名單",
                "還沒按「⬇️ 更新名單」。\n\n"
                "程式跑的是本機那份 CSV 抄本，不更新的話，你在線上名單新增的商品\n"
                "不會出現在下面的勾選清單裡（看起來一切正常，但那幾支不會被做）。\n\n"
                "先按「⬇️ 更新名單」，這顆才會變綠色。")
            return
        if not self._guard():
            return
        if not self._shop().cookie_path.exists():
            messagebox.showerror("錯誤", f"{_SHOP_LABELS[self.shop_var.get()]} 還沒有 1688 登入。\n\n"
                                 + _RELOGIN_HINT)
            return
        sel = self._guard_selection()
        if sel is None:
            return
        if not self._warn_no_category(sel):
            return
        if not self._block_missing_stock(sel):
            return
        if not self._warn_gpt(sel):
            return
        staging = self._staging_precheck()
        if staging is None:
            return
        # 按下去之前先把「這次會做什麼」攤開來講 —— 不要讓人從勾選去推
        plan = self._plan(sel)
        if not messagebox.askyesno("確認這次要做的事", self._plan_text(plan) + "\n\n開始嗎？"):
            return
        # 已經有文案的就沿用（同一個模板才算）——重生文案是第二段的明確動作，不在這裡偷偷發生
        for p in sel:
            p["reuse_content"] = bool((self.status.get(p["code"]) or {}).get("文案"))
        self._busy(True, cancellable=True)
        self.cancel_event.clear()
        self._log(f"🚀 開始：{len(sel)} 商品（缺什麼補什麼）…")
        threading.Thread(target=self._run_all_worker, args=(sel, *staging), daemon=True).start()

    def _run_all_worker(self, products: list[dict], make_staging: bool = False,
                        staging_force: bool = False) -> None:
        from scraper.playwright_scraper import scrape_many
        from scraper.batch_pipeline2 import run_batch_two_tier
        shop = self.shop_var.get()
        try:
            # ① 抓取（已抓過就不重抓——勾了那顆的話）
            ids = [p["item_id"] for p in products]
            # 一鍵＝缺什麼補什麼：抓過的一律跳過；**舊版抓取器抓的算缺**（例：沒有規格圖）。
            # 要強制更新 1688 資料走「🔄 重抓 1688」。
            from scraper.playwright_scraper import raw_is_fresh
            ids = list(dict.fromkeys(str(i) for i in ids))
            old = [i for i in ids if (Path(RAW_DIR) / f"{i}.json").exists()
                   and not raw_is_fresh(Path(RAW_DIR) / f"{i}.json")]
            have = [i for i in ids if raw_is_fresh(Path(RAW_DIR) / f"{i}.json")]
            ids = [i for i in ids if i not in have]
            if have:
                self._thread_log(f"① 已抓過 {len(have)} 支，跳過（要更新 1688 資料按「🔄 重抓 1688」）")
            if old:
                self._thread_log(f"① {len(old)} 支是舊版抓取器抓的（缺規格圖等）→ 重抓")
            if not ids:
                self._thread_log("① 全部都抓過了 → 直接產出")
                res = {"success": len(products), "blocked": 0, "failed": 0}
            else:
                self._thread_log(f"① 去 1688 抓 {len(ids)} 商品…")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    res = loop.run_until_complete(scrape_many(
                        ids, cookie_path=self._shop().cookie_path, out_dir=Path(RAW_DIR),
                        headless=False, progress_cb=self._thread_log,
                        cancel_check=self.cancel_event.is_set))
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
                self._thread_log(f"① 抓取完成：成功 {res['success']} / 被擋 {res['blocked']} / 失敗 {res['failed']}")
            if self.cancel_event.is_set():
                self._thread_log("已取消，未產出")
                return
            if res["success"] == 0:
                self._thread_log("① 一個都沒抓到（cookie 可能過期）→ 停止，未產出")
                self.root.after(0, self._prompt_relogin)
                return
            # ② 產出（run_batch_two_tier 內部自帶 asyncio.run，須無 running loop）
            self._thread_log(f"② 產出 {len(products)} 商品（文案+挑色+影片+Excel）…")
            res2 = run_batch_two_tier(json_dir=Path(RAW_DIR), sop_override=self._sop_override(),
                                      img_template=self._img_template(),
                                      make_video=self.make_video.get(), products=products,
                                      shop=shop, make_staging=make_staging,
                                      staging_force=staging_force, mode="start")
            self._report_batch(res2)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            from scraper.master_staging import SpecGapBlocked
            if isinstance(e, SpecGapBlocked):
                # 守門員：既有列規格空白會重發品號 → 擋下來並把要做什麼講清楚
                self._thread_log("⛔ 配號守門員擋下：既有列的 1688 規格原文是空的（未產出）")
                self.root.after(0, lambda m=str(e): messagebox.showerror("⛔ 先補 1688 規格再跑", m))
            else:
                self._thread_log(f"一鍵完成錯誤：{e}")
        finally:
            self.root.after(0, self._rescan_and_redraw)
            self.root.after(0, self._on_task_done)

    def _report_batch(self, res: dict) -> None:
        self._thread_log(f"✅ 完成：{res['success']}/{res['total']} 成功，失敗 {res['failed']}")
        for m in res.get("products", []):
            vtag = " | 🎬" if m.get("video") else ""
            self._thread_log(f"    ✓ {m['code']}: {m['sku_count']} SKU{vtag} | {m['title'][:24]}")
        for f in res.get("failures", []):
            self._thread_log(f"    ✗ {f['code']}: {f['error']}")
        st = res.get("staging")
        if st:
            self._thread_log(f"🆕 待貼分頁：{st['written']} 商品 / {st['sku_rows']} SKU 列 → "
                             f"1-1「{st['tab']}」（補黃底欄後貼進商品表/SKU表）")
        ck = res.get("check_sheet")
        if ck and ck.get("error"):
            self._thread_log(f"⚠️ 上架核對表沒寫進去：{ck['error']}")
        elif ck:
            self._thread_log(f"📋 上架核對表：分頁「{ck['tab']}」新增 {ck['added']} 支、更新 {ck['updated']} 支")
        bdir = res.get("batch_dir")
        if bdir:
            try:    # 名單快照：這批是拿哪一版名單跑的，事後對得回去
                import shutil
                csv = Path(self.csv_path.get())
                if csv.exists():
                    shutil.copy2(csv, Path(bdir) / "名單快照.csv")
            except Exception as e:  # noqa: BLE001
                self._thread_log(f"⚠️ 名單快照沒存成：{e}")
            self._thread_log(f"📁 這批的資料夾：{bdir}（{res.get('version','')}）")
        excel = res.get("excel_path")
        if res.get("mode") == "staging":
            self._thread_log("📄 上架檔不動（這顆只重建 1-1 與核對表）")
        if excel:
            self._thread_log(f"📄 蝦皮 Excel：{excel}")
            self.root.after(0, self._prompt_open_excel, Path(excel))

    # ── 🔍 只抓取 ──────────────────────────────
    def _on_scrape(self) -> None:
        if not self._guard():
            return
        if not self._shop().cookie_path.exists():
            messagebox.showerror("錯誤", f"{_SHOP_LABELS[self.shop_var.get()]} 還沒有 1688 登入。\n\n"
                                 + _RELOGIN_HINT)
            return
        sel = self._guard_selection()
        if sel is None:
            return
        item_ids = [p["item_id"] for p in sel]
        self._busy(True, cancellable=True)
        self.cancel_event.clear()
        self._log(f"開始抓取 {len(item_ids)} 個勾選商品…")
        threading.Thread(target=self._scrape_worker, args=(item_ids,), daemon=True).start()

    def _scrape_worker(self, item_ids: list[str]) -> None:
        from scraper.playwright_scraper import scrape_many
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(scrape_many(
                item_ids, cookie_path=self._shop().cookie_path, out_dir=Path(RAW_DIR),
                headless=False, progress_cb=self._thread_log,
                cancel_check=self.cancel_event.is_set))
            self._thread_log(
                f"✅ 抓取完成：成功 {res['success']} / 被擋 {res['blocked']} / 失敗 {res['failed']}")
            if res["blocked"]:
                self.root.after(0, self._prompt_relogin)
        except Exception as e:  # noqa: BLE001
            self._thread_log(f"抓取錯誤：{e}")
        finally:
            loop.close()
            self.root.after(0, self._on_task_done)

    def _prompt_relogin(self) -> None:
        messagebox.showwarning("可能被擋 / cookie 過期", _RELOGIN_HINT)

    # ── 分步重生（Edwin 2026-09-19：只換一樣、其餘沿用上一版）──────────────
    #
    # 三顆都只處理「有勾的商品」，而且前提是那幾支都按過 🚀 開始（整套齊全）：
    # 沒有上一版上架檔／沒建 1-1 的商品一律擋——否則會出現「蝦皮有這一版、1-1 沒有品號」。
    def _prereq_ok(self, sel: list[dict], mode: str) -> bool:
        from scraper.batch_pipeline2 import missing_prereqs
        try:
            miss = missing_prereqs(self.shop_var.get(), sel, mode)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("檢查失敗", f"讀不到上一版的紀錄：{e}")
            return False
        if miss:
            lines = "\n".join(f"　{c}：{'、'.join(w)}" for c, w in list(miss.items())[:15])
            more = f"\n　…共 {len(miss)} 支" if len(miss) > 15 else ""
            messagebox.showerror(
                "先按「🚀 開始」",
                f"這幾支還沒整套做過（抓取＋文案＋1-1 品號＋上架檔）：\n\n{lines}{more}\n\n"
                "分步重生是「只換一樣、其餘沿用上一版」，沒有上一版就沒得沿用。\n"
                "先勾這幾支按「🚀 開始」，做完再回來重生。")
            return False
        return True

    def _on_regen_copy(self) -> None:
        if not self._guard():
            return
        sel = self._guard_selection()
        if sel is None or not self._prereq_ok(sel, "copy"):
            return
        if not messagebox.askyesno(
            "✏️ 重生文案",
            f"{len(sel)} 支商品用文案模板「{self.sop_var.get()}」重寫標題＋詳情。\n\n"
            "· 圖片、SKU 品號沿用上一版（1-1、核對表都不動）\n"
            "· 產出新一版上架檔（只含這幾支），舊版完整保留\n"
            "· 到蝦皮刪掉這幾支的舊版，再匯入新的\n\n開始嗎？"):
            return
        self._start_step(sel, "copy", f"✏️ 重生文案（{len(sel)} 支，模板 {self.sop_var.get()}）…")

    def _on_regen_images(self) -> None:
        if not self._guard():
            return
        sel = self._guard_selection()
        if sel is None or not self._prereq_ok(sel, "images"):
            return
        tpl = self._img_template_obj()
        if tpl is None:
            messagebox.showerror(
                "還沒有圖片模板",
                f"{_SHOP_LABELS[self.shop_var.get()]} 還沒有圖片模板。\n\n"
                f"模板放在 config/design_engine/{self.shop_var.get()}/ 底下（.md），"
                "放一份進去下拉選單就會出現。")
            return
        from scraper.image_templates import PRICE_PER_IMAGE
        n_img = len(sel) * tpl.count
        cost = n_img * PRICE_PER_IMAGE
        if not messagebox.askyesno(
            "🖼️ 重生圖片（GPT）",
            f"{len(sel)} 支商品用圖片模板「{tpl.name}」重新生圖（每支 {tpl.label}）。\n\n"
            f"· 共 {n_img} 張，約 US${cost:.2f}（台幣 {cost * 32:.0f} 元）\n"
            "· 文案、SKU 品號沿用上一版（1-1、核對表都不動）\n"
            "· 某一張沒生成功 → 那一格沿用 1688 原圖\n"
            "· 產出新一版上架檔（只含這幾支），舊版與舊圖完整保留\n\n開始嗎？"):
            return
        self._start_step(sel, "images", f"🖼️ 重生圖片（{len(sel)} 支 × {tpl.label}，模板 {tpl.name}）…")

    def _on_rebuild_staging(self) -> None:
        if not self._guard():
            return
        sel = self._guard_selection()
        if sel is None or not self._prereq_ok(sel, "staging"):
            return
        if not self._block_missing_stock(sel):
            return
        staging = self._staging_precheck()
        if staging is None:
            return
        if not messagebox.askyesno(
            "🆕 重建 1-1",
            f"{len(sel)} 支商品重新寫一份 1-1「_待貼新品」＋上架核對表。\n\n"
            "· 上架檔完全不動（不產新版）\n"
            "· 配出來的品號必須跟上一版上架檔一模一樣，不一樣就停下來告訴你\n\n開始嗎？"):
            return
        self._start_step(sel, "staging", f"🆕 重建 1-1（{len(sel)} 支）…", staging_force=staging[1])

    def _start_step(self, sel: list[dict], mode: str, msg: str, staging_force: bool = False) -> None:
        self._busy(True)
        self._log(msg)
        threading.Thread(target=self._step_worker, args=(sel, mode, staging_force), daemon=True).start()

    def _step_worker(self, products: list[dict], mode: str, staging_force: bool = False) -> None:
        from scraper.batch_pipeline2 import OptionMismatch, run_batch_two_tier
        from scraper.master_staging import SpecGapBlocked
        try:
            res = run_batch_two_tier(json_dir=Path(RAW_DIR), sop_override=self._sop_override(),
                                     img_template=self._img_template(),
                                     make_video=self.make_video.get(), products=products,
                                     shop=self.shop_var.get(), make_staging=True,
                                     staging_force=staging_force, mode=mode)
            self._report_batch(res)
        except OptionMismatch as e:
            self._thread_log("⛔ 選項跟 1-1 對不上 → 停下來，什麼都沒寫")
            if mode == "staging":
                self.root.after(0, self._offer_staging_excel, products, str(e), staging_force)
            else:
                self.root.after(0, lambda m=str(e): messagebox.showerror("⛔ 上架檔跟 1-1 對不上", m))
        except SpecGapBlocked as e:
            self._thread_log("⛔ 配號守門員擋下：既有列的 1688 規格原文是空的（未寫入）")
            self.root.after(0, lambda m=str(e): messagebox.showerror("⛔ 先補 1688 規格再跑", m))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._thread_log(f"執行錯誤：{e}")
            self.root.after(0, lambda m=str(e): messagebox.showerror("執行錯誤", m))
        finally:
            self.root.after(0, self._rescan_and_redraw)
            self.root.after(0, self._on_task_done)

    def _offer_staging_excel(self, products: list[dict], msg: str, staging_force: bool) -> None:
        """重建 1-1 發現選項變了 → 問要不要 1-1 與上架檔一起換（兩邊永遠一對一）。"""
        if messagebox.askyesno(
            "選項變了：1-1 和上架檔要一起換嗎？",
            msg + "\n\n按「是」＝重建 1-1，同時產一版新的上架檔（文案、圖沿用），"
                  "兩邊用同一份品號。\n按「否」＝什麼都不做。"):
            self._busy(True)
            self._log(f"🆕 重建 1-1＋新版上架檔（{len(products)} 支）…")
            threading.Thread(target=self._step_worker,
                             args=(products, "staging_excel", staging_force), daemon=True).start()

    def _prompt_open_excel(self, excel: Path) -> None:
        if messagebox.askyesno("完成", f"蝦皮 Excel 已產出：\n{excel}\n\n要打開它所在的資料夾嗎？"):
            _open_path(excel.parent)

    # ── 📁 素材夾 ──────────────────────────────
    def _latest_batch_dir(self) -> Path | None:
        """這個賣場最後跑的那一批資料夾（batch/{shop}/{YYYYMMDD}/）。"""
        base = Path(BATCH_DIR) / self.shop_var.get()
        dirs = sorted([d for d in base.glob("*") if d.is_dir()], reverse=True) if base.exists() else []
        return dirs[0] if dirs else None

    def _on_open_assets(self) -> None:
        """開最新那批的資料夾（上架檔／素材／manifest 都在裡面）；還沒跑過就開 batch 根目錄。"""
        target = self._latest_batch_dir() or Path(BATCH_DIR)
        target.mkdir(parents=True, exist_ok=True)
        _open_path(target)

    # ── 其他 ──────────────────────────────
    def _on_stop(self) -> None:
        self.cancel_event.set()
        self.stop_btn.config(state="disabled")
        self._status("正在停止，等目前這筆處理完…")

    def _on_task_done(self) -> None:
        self._busy(False)
        self.cancel_event.clear()
        self._refresh_cookie_status()
        self._save_state()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
