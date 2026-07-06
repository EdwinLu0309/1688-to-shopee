"""
1688 → 蝦皮 上架小幫手 — GUI 啟動器（仿 1688-order launcher）

一條龍：⬇️ 更新名單 → 勾選商品 → 🚀 一鍵完成（抓取→產出）→ 📁 素材夾。
（🔍 抓取、📦 產出 也可分步個別按；🔑 登入 1688 首次/過期時用。）

按鈕對應：
  ⬇️ 更新名單  sheet_fetcher.fetch_ai_list（路 B：解密 Chrome Google cookie 抓私有 Sheet）
  🚀 一鍵完成  勾選商品 → scrape_many（抓）→ run_batch_two_tier（產）一次到底
  🔑 登入 1688 playwright_scraper.save_cookies → config/cookies.json
  🔍 抓取商品  playwright_scraper.scrape_many（去 1688 下載資料/圖）→ output/{id}.json
  📦 產出上架檔 batch_pipeline2.run_batch_two_tier（文案+挑色+影片+蝦皮 Excel）
  📁 素材夾    output/上架素材/（影片+尺寸表，蝦皮 Excel 無影片欄，手動補）

跨平台：GUI 邏輯 Win/Mac 皆可；「更新名單」的 cookie 解密目前只實作 macOS。
"""
import asyncio
import json
import os
import platform
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)
sys.path.insert(0, str(BASE_DIR))

from config.settings import OUTPUT_DIR  # noqa: E402
from scraper.playwright_scraper import COOKIE_PATH  # noqa: E402

STATE_PATH = BASE_DIR / "config" / "gui_state.json"
DEFAULT_CSV = BASE_DIR / "input" / "lady_ai_list.csv"
ASSETS_DIR = Path(OUTPUT_DIR) / "上架素材"

_CAT_NAME = {"100358": "長褲", "100103": "牛仔褲", "100360": "短褲",
             "100361": "褲裙", "100102": "裙裝", "100352": "上衣",
             "100356": "上衣", "100353": "襯衫", "": "❌無分類"}

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
        self.csv_path = tk.StringVar(value=str(self._load_last_csv()))
        self.make_video = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就緒")

        self.products: list[dict] = []
        self.check_vars: list[tk.BooleanVar] = []
        self.action_buttons: list[tk.Button] = []

        self._build_ui()
        self.root.minsize(760, 860)
        self._refresh_cookie_status()
        self._refresh_products()
        self._center_window()

    # ── 狀態記憶 ──────────────────────────────
    def _load_last_csv(self) -> Path:
        if STATE_PATH.exists():
            try:
                p = json.loads(STATE_PATH.read_text(encoding="utf-8")).get("csv_path", "")
                if p and Path(p).exists():
                    return Path(p)
            except Exception:  # noqa: BLE001
                pass
        return DEFAULT_CSV

    def _save_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            STATE_PATH.write_text(
                json.dumps({"csv_path": self.csv_path.get()}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ── UI ──────────────────────────────
    def _build_ui(self) -> None:
        BG, FG = self.BG, self.FG

        tk.Label(self.root, text="1688 → 蝦皮 上架小幫手",
                 font=F_TITLE, pady=10, bg=BG, fg=FG).pack()

        # ── 名單 + 更新 ──
        csv_frame = tk.Frame(self.root, padx=24, pady=4, bg=BG)
        csv_frame.pack(fill="x")
        tk.Label(csv_frame, text="① 名單：", font=F_LBL_B, bg=BG, fg=FG).pack(side="left")
        tk.Entry(csv_frame, textvariable=self.csv_path, font=("Arial", 12), width=24,
                 bg="#ffffff", fg="#111111").pack(side="left", fill="x", expand=True, padx=4)
        tk.Button(csv_frame, text="選檔…", font=F_BTN_SM,
                  command=self._on_pick_csv).pack(side="left", padx=(0, 6))
        self.fetch_btn = tk.Button(csv_frame, text="⬇️ 更新名單", font=F_BTN,
                                   command=self._on_fetch_list)
        self.fetch_btn.pack(side="left")
        self.action_buttons.append(self.fetch_btn)
        tk.Label(self.root, text="（⬇️ 更新名單＝直接連你 Chrome 的 Google 帳號抓最新線上表，免登入）",
                 font=F_HINT, fg="#888", bg=BG).pack(anchor="w", padx=24)

        # ── 商品勾選清單 ──
        list_lbl = tk.Frame(self.root, padx=24, pady=6, bg=BG)
        list_lbl.pack(fill="x")
        tk.Label(list_lbl, text="② 勾選要處理的商品：", font=F_LBL_B, bg=BG, fg=FG).pack(side="left")
        self.count_var = tk.StringVar(value="尚未載入名單")
        tk.Label(list_lbl, textvariable=self.count_var, font=F_LBL, bg=BG, fg="#1a7f37").pack(side="left", padx=8)
        tk.Button(list_lbl, text="全不選", font=F_BTN_SM,
                  command=lambda: self._set_all_checks(False)).pack(side="right", padx=3)
        tk.Button(list_lbl, text="全選", font=F_BTN_SM,
                  command=lambda: self._set_all_checks(True)).pack(side="right", padx=3)

        list_outer = tk.Frame(self.root, padx=24, bg=BG)
        list_outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(list_outer, height=210, bg="#ffffff",
                                highlightthickness=1, highlightbackground="#ccc")
        scroll = tk.Scrollbar(list_outer, orient="vertical", command=self.canvas.yview)
        self.checks_frame = tk.Frame(self.canvas, bg="#ffffff")
        self.checks_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.checks_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 3)), "units"))

        # ── 一鍵完成（主按鈕）──
        hero = tk.Frame(self.root, padx=24, pady=8, bg=BG)
        hero.pack(fill="x")
        self.run_all_btn = tk.Button(hero, text="🚀 一鍵完成（抓取 → 產出上架檔）",
                                     font=F_BTN_HERO, bg="#1a7f37", fg="#ffffff",
                                     activebackground="#15682d", activeforeground="#ffffff",
                                     height=2, command=self._on_run_all)
        self.run_all_btn.pack(fill="x")
        self.action_buttons.append(self.run_all_btn)
        tk.Label(self.root, text="③ 勾好商品按這顆：自動去 1688 抓資料，再做文案+挑色+影片+蝦皮 Excel，一次到底",
                 font=F_HINT, fg="#888", bg=BG).pack(anchor="w", padx=24)

        tk.Checkbutton(self.root, text="產出時順便合成短影片（缺圖自動下載）", variable=self.make_video,
                       font=F_HINT, bg=BG, fg=FG, selectcolor="#ffffff",
                       activebackground=BG).pack(anchor="w", padx=24, pady=(2, 4))

        # ── 分步 / 其他 ──
        tk.Label(self.root, text="分步執行（需要時才個別按）：", font=F_HINT, fg="#666",
                 bg=BG).pack(anchor="w", padx=24, pady=(4, 0))
        steps = tk.Frame(self.root, padx=24, pady=2, bg=BG)
        steps.pack(fill="x")

        def step_btn(text, cmd):
            b = tk.Button(steps, text=text, font=F_BTN_SM, command=cmd)
            b.pack(side="left", padx=(0, 6))
            self.action_buttons.append(b)
            return b

        step_btn("🔑 登入 1688", self._on_login)
        step_btn("🔍 只抓取", self._on_scrape)
        step_btn("📦 只產出", self._on_run)
        step_btn("📁 素材夾", self._on_open_assets)

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
        self.stop_btn = tk.Button(bottom, text="⏹ 停止", font=F_BTN_SM, width=8,
                                  state="disabled", command=self._on_stop)
        self.stop_btn.pack(side="right")
        tk.Label(bottom, textvariable=self.status_var, font=F_STATUS, fg="#555", bg=BG,
                 wraplength=560, justify="left", anchor="w").pack(side="left", fill="x", expand=True)
        tk.Frame(self.root, height=8, bg=BG).pack()

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
        self.products, self.check_vars = [], []

        csv = Path(self.csv_path.get())
        if not csv.exists():
            self.count_var.set("尚未載入名單（按「⬇️ 更新名單」）")
            return
        try:
            from scraper.ai_list_reader import parse_ai_list_csv
            self.products = parse_ai_list_csv(csv)
        except Exception as e:  # noqa: BLE001
            self.count_var.set(f"名單解析失敗：{e}")
            return

        for p in self.products:
            var = tk.BooleanVar(value=False)
            self.check_vars.append(var)
            cat = _CAT_NAME.get(p.get("category", ""), p.get("category", ""))
            warn = "" if p.get("category") else " ⚠️"
            label = f"{p['code']}　[{cat}{warn}]　{p.get('name','')[:20]}"
            tk.Checkbutton(self.checks_frame, text=label, variable=var, anchor="w",
                           font=F_CHK, bg="#ffffff", fg="#111111", selectcolor="#ffffff",
                           activebackground="#f0f0f0", command=self._update_count,
                           padx=4, pady=2).pack(fill="x", anchor="w")
        self._update_count()

    def _set_all_checks(self, val: bool) -> None:
        for v in self.check_vars:
            v.set(val)
        self._update_count()

    def _update_count(self) -> None:
        sel = sum(1 for v in self.check_vars if v.get())
        self.count_var.set(f"名單 {len(self.products)} 筆，已勾 {sel} 筆")

    def _selected(self) -> list[dict]:
        return [p for p, v in zip(self.products, self.check_vars) if v.get()]

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
        if COOKIE_PATH.exists():
            try:
                n = len(json.loads(COOKIE_PATH.read_text(encoding="utf-8")))
                self.cookie_status.config(text=f"✅ 已登入（{n} 筆）", fg="#1a7f37")
            except Exception:  # noqa: BLE001
                self.cookie_status.config(text="⚠️ cookie 檔壞了", fg="#cf222e")
        else:
            self.cookie_status.config(text="❌ 未登入（先按「🔑 登入 1688」）", fg="#cf222e")

    def _busy(self, on: bool, cancellable: bool = False) -> None:
        self.running = on
        self._set_buttons("disabled" if on else "normal")
        self.stop_btn.config(state="normal" if (on and cancellable) else "disabled")

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

    # ── ⬇️ 更新名單 ──────────────────────────────
    def _on_fetch_list(self) -> None:
        if not self._guard():
            return
        self._busy(True)
        self._log("連線你 Chrome 的 Google 帳號抓最新名單…（首次會跳鑰匙圈授權，請按允許）")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self) -> None:
        try:
            from scraper.sheet_fetcher import fetch_ai_list
            out = Path(self.csv_path.get()) if self.csv_path.get() else None
            res = fetch_ai_list(out_path=out)
            if res.get("ok"):
                self._thread_log(f"✅ 名單已更新（設定檔 {res['profile']}，{res['bytes']} bytes）")
                self.root.after(0, self._refresh_products)
            else:
                self._thread_log(f"❌ 抓取失敗：{res.get('error')}")
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._thread_log(f"更新名單錯誤：{e}")
        finally:
            self.root.after(0, self._on_task_done)

    # ── 🚀 一鍵完成 ──────────────────────────────
    def _on_run_all(self) -> None:
        if not self._guard():
            return
        if not COOKIE_PATH.exists():
            messagebox.showerror("錯誤", "還沒登入 1688，請先按「🔑 登入 1688」")
            return
        sel = self._guard_selection()
        if sel is None:
            return
        if not self._warn_no_category(sel):
            return
        self._busy(True, cancellable=True)
        self.cancel_event.clear()
        self._log(f"🚀 一鍵完成：{len(sel)} 商品（① 抓取 → ② 產出）…")
        threading.Thread(target=self._run_all_worker, args=(sel,), daemon=True).start()

    def _run_all_worker(self, products: list[dict]) -> None:
        from scraper.playwright_scraper import scrape_many
        from scraper.batch_pipeline2 import run_batch_two_tier
        try:
            # ① 抓取
            ids = [p["item_id"] for p in products]
            self._thread_log(f"① 去 1688 抓 {len(ids)} 商品…")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                res = loop.run_until_complete(scrape_many(
                    ids, cookie_path=COOKIE_PATH, out_dir=Path(OUTPUT_DIR),
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
            res2 = run_batch_two_tier(json_dir=Path(OUTPUT_DIR),
                                      make_video=self.make_video.get(), products=products)
            self._report_batch(res2)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._thread_log(f"一鍵完成錯誤：{e}")
        finally:
            self.root.after(0, self._on_task_done)

    def _report_batch(self, res: dict) -> None:
        self._thread_log(f"✅ 完成：{res['success']}/{res['total']} 成功，失敗 {res['failed']}")
        for m in res.get("products", []):
            vtag = " | 🎬" if m.get("video") else ""
            self._thread_log(f"    ✓ {m['code']}: {m['sku_count']} SKU{vtag} | {m['title'][:24]}")
        for f in res.get("failures", []):
            self._thread_log(f"    ✗ {f['code']}: {f['error']}")
        excel = res.get("excel_path")
        if excel:
            self._thread_log(f"📄 蝦皮 Excel：{excel}")
            self.root.after(0, self._prompt_open_excel, Path(excel))

    # ── 🔑 登入 ──────────────────────────────
    def _on_login(self) -> None:
        if not self._guard():
            return
        if not messagebox.askyesno("登入 1688",
                                   "即將開瀏覽器讓你登入 1688，登入後自動存 cookie。\n\n繼續嗎？"):
            return
        self._busy(True)
        self._log("開瀏覽器登入 1688…（最多等 5 分鐘）")
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self) -> None:
        from scraper.playwright_scraper import save_cookies
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            n = loop.run_until_complete(save_cookies(COOKIE_PATH))
            self._thread_log(f"✅ 登入完成，已存 {n} 筆 cookie")
        except Exception as e:  # noqa: BLE001
            self._thread_log(f"登入錯誤：{e}")
        finally:
            loop.close()
            self.root.after(0, self._on_task_done)

    # ── 🔍 只抓取 ──────────────────────────────
    def _on_scrape(self) -> None:
        if not self._guard():
            return
        if not COOKIE_PATH.exists():
            messagebox.showerror("錯誤", "還沒登入，請先按「🔑 登入 1688」")
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
                item_ids, cookie_path=COOKIE_PATH, out_dir=Path(OUTPUT_DIR),
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
        if messagebox.askyesno("可能被擋 / cookie 過期",
                               "有商品抓到 0 主圖（cookie 可能過期）。要現在重新登入嗎？"):
            self._on_login()

    # ── 📦 只產出 ──────────────────────────────
    def _on_run(self) -> None:
        if not self._guard():
            return
        sel = self._guard_selection()
        if sel is None:
            return
        missing = [p["code"] for p in sel
                   if not (Path(OUTPUT_DIR) / f"{p['item_id']}.json").exists()
                   and not (Path(OUTPUT_DIR) / p["item_id"] / f"{p['item_id']}.json").exists()]
        if missing:
            if not messagebox.askyesno(
                "缺抓取資料",
                f"這些勾選商品還沒抓取（缺 JSON）：\n{', '.join(missing)}\n\n"
                "缺的會被跳過。要繼續嗎？（建議先按「🔍 只抓取」或用「🚀 一鍵完成」）"):
                return
        if not self._warn_no_category(sel):
            return
        self._busy(True)
        self._log(f"開始產出（{len(sel)} 個勾選商品，影片={'開' if self.make_video.get() else '關'}）…")
        threading.Thread(target=self._run_worker, args=(sel,), daemon=True).start()

    def _run_worker(self, products: list[dict]) -> None:
        from scraper.batch_pipeline2 import run_batch_two_tier
        try:
            res = run_batch_two_tier(json_dir=Path(OUTPUT_DIR),
                                     make_video=self.make_video.get(), products=products)
            self._report_batch(res)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._thread_log(f"執行錯誤：{e}")
        finally:
            self.root.after(0, self._on_task_done)

    def _prompt_open_excel(self, excel: Path) -> None:
        if messagebox.askyesno("完成", f"蝦皮 Excel 已產出：\n{excel}\n\n要打開它所在的資料夾嗎？"):
            _open_path(excel.parent)

    # ── 📁 素材夾 ──────────────────────────────
    def _on_open_assets(self) -> None:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        _open_path(ASSETS_DIR)

    # ── 其他 ──────────────────────────────
    def _on_pick_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="選 AI 上架名單 CSV",
            initialdir=str((BASE_DIR / "input") if (BASE_DIR / "input").exists() else BASE_DIR),
            filetypes=[("CSV", "*.csv"), ("所有檔案", "*.*")])
        if path:
            self.csv_path.set(path)
            self._save_state()
            self._refresh_products()

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
