"""
1688 → 蝦皮 上架小幫手 — GUI 啟動器（仿 1688-order launcher）

一條龍：選 AI 上架名單 CSV → 🔑 登入 1688 → 🔍 抓取（Playwright+cookie）→
▶ 執行（batch2 文案+變體+影片 → 合併蝦皮 Excel）→ 📁 開素材夾補影片/尺寸表。

四顆按鈕對應 #S066 規劃的「登入按鈕→App 自己抓」全包流程：
  🔑 登入  scraper.playwright_scraper.save_cookies  → config/cookies.json
  🔍 抓取  scraper.playwright_scraper.scrape_many   → output/{item_id}.json
  ▶ 執行  scraper.batch_pipeline2.run_batch_two_tier（吃 ai_list_reader 的輸出）
  📁 素材  開 output/上架素材/（影片+尺寸表，蝦皮 Excel 無影片欄，手動補）

跨平台：Win/Mac 皆可（run_mac.command / run_windows.bat）。深色模式配色沿用 launcher。
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


def _open_path(path: Path) -> None:
    """用系統檔案總管開啟資料夾/檔案（跨平台）。"""
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
        self.root.resizable(False, False)

        # macOS 深色模式下 tk 原生 widget 會與系統配色撞色變隱形，統一 palette + 明確 bg/fg
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

        self.action_buttons: list[tk.Button] = []
        self._build_ui()
        self.root.minsize(560, 0)
        self._refresh_cookie_status()
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
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    # ── UI ──────────────────────────────
    def _build_ui(self) -> None:
        BG, FG = self.BG, self.FG

        tk.Label(self.root, text="1688 → 蝦皮 上架小幫手",
                 font=("Arial", 17, "bold"), pady=10, bg=BG, fg=FG).pack()

        # AI 名單選擇
        csv_frame = tk.Frame(self.root, padx=20, pady=4, bg=BG)
        csv_frame.pack(fill="x")
        tk.Label(csv_frame, text="AI 上架名單 CSV：", font=("Arial", 11),
                 bg=BG, fg=FG).pack(side="left")
        tk.Entry(csv_frame, textvariable=self.csv_path, font=("Arial", 10),
                 width=38, bg="#ffffff", fg="#111111").pack(
                     side="left", fill="x", expand=True, padx=(4, 4))
        tk.Button(csv_frame, text="選檔…", font=("Arial", 10),
                  command=self._on_pick_csv).pack(side="left")

        tk.Label(self.root,
                 text="（從已登入 Chrome 同源下載「【Lady】AI 上架名單」CSV，放進 input/）",
                 font=("Arial", 9), fg="#888", bg=BG).pack(anchor="w", padx=20)

        # Cookie 狀態
        cookie_frame = tk.Frame(self.root, padx=20, pady=6, bg=BG)
        cookie_frame.pack(fill="x")
        tk.Label(cookie_frame, text="1688 登入 Cookie：", font=("Arial", 11),
                 bg=BG, fg=FG).pack(side="left")
        self.cookie_status = tk.Label(cookie_frame, text="", font=("Arial", 11, "bold"), bg=BG)
        self.cookie_status.pack(side="left")

        sep = tk.Frame(self.root, height=1, bg="#ccc")
        sep.pack(fill="x", padx=20, pady=8)

        # 四顆主按鈕（步驟排列）
        steps_frame = tk.Frame(self.root, padx=20, bg=BG)
        steps_frame.pack(fill="x")

        def step_row(label: str, btn_text: str, cmd, hint: str):
            row = tk.Frame(steps_frame, bg=BG)
            row.pack(fill="x", pady=5)
            btn = tk.Button(row, text=btn_text, font=("Arial", 13), width=14, command=cmd)
            btn.pack(side="left")
            self.action_buttons.append(btn)
            tk.Label(row, text=hint, font=("Arial", 10), fg="#666", bg=BG,
                     anchor="w", justify="left", wraplength=340).pack(
                         side="left", padx=(12, 0), fill="x", expand=True)
            return btn

        step_row("① 登入", "🔑 登入 1688", self._on_login,
                 "開瀏覽器手動登入 1688，存 cookie（首次或 cookie 過期時做）")
        step_row("② 抓取", "🔍 抓取商品", self._on_scrape,
                 "讀 AI 名單，Playwright+cookie 逐一抓 → output/{id}.json")
        step_row("③ 執行", "▶ 產出 Excel", self._on_run,
                 "Claude 文案+變體+影片 → 合併一個蝦皮上架 Excel")
        step_row("④ 素材", "📁 開素材夾", self._on_open_assets,
                 "影片+尺寸表（Excel 無影片欄）按編號歸檔，手動補上蝦皮")

        tk.Checkbutton(steps_frame, text="執行時順便合成短影片（缺圖自動下載）",
                       variable=self.make_video, font=("Arial", 10),
                       bg=BG, fg=FG, selectcolor="#ffffff",
                       activebackground=BG).pack(anchor="w", pady=(2, 0))

        sep2 = tk.Frame(self.root, height=1, bg="#ccc")
        sep2.pack(fill="x", padx=20, pady=8)

        # 日誌
        log_frame = tk.Frame(self.root, padx=20, bg=BG)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=9, font=("Menlo", 10), wrap="word",
                                relief="solid", borderwidth=1, bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="#d4d4d4", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        # 底部：狀態 + 停止
        bottom = tk.Frame(self.root, padx=20, pady=6, bg=BG)
        bottom.pack(fill="x")
        self.stop_btn = tk.Button(bottom, text="⏹ 停止", font=("Arial", 11),
                                  width=8, state="disabled", command=self._on_stop)
        self.stop_btn.pack(side="right")
        tk.Label(bottom, textvariable=self.status_var, font=("Arial", 11), fg="#555",
                 bg=BG, wraplength=380, justify="left", anchor="w").pack(
                     side="left", fill="x", expand=True)
        tk.Frame(self.root, height=8, bg=BG).pack()

    def _center_window(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

    # ── 共用 helpers ──────────────────────────────
    def _log(self, msg: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _thread_log(self, msg: str) -> None:
        """從 worker thread 安全更新 UI。"""
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
            self.cookie_status.config(text="❌ 未登入（先按「🔑 登入」）", fg="#cf222e")

    def _busy(self, on: bool, cancellable: bool = False) -> None:
        self.running = on
        self._set_buttons("disabled" if on else "normal")
        self.stop_btn.config(state="normal" if (on and cancellable) else "disabled")

    def _guard(self) -> bool:
        if self.running:
            messagebox.showwarning("提示", "有任務正在執行中，請等待完成")
            return False
        return True

    def _read_products(self) -> list[dict] | None:
        """讀 AI 名單 CSV → products；失敗回 None 並提示。"""
        csv = Path(self.csv_path.get())
        if not csv.exists():
            messagebox.showerror("錯誤", f"找不到 AI 名單 CSV：\n{csv}")
            return None
        try:
            from scraper.ai_list_reader import parse_ai_list_csv
            products = parse_ai_list_csv(csv)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("錯誤", f"解析 CSV 失敗：\n{e}")
            return None
        if not products:
            messagebox.showwarning("提示", "AI 名單沒有可用商品（缺網址或編號？）")
            return None
        return products

    # ── ① 登入 ──────────────────────────────
    def _on_login(self) -> None:
        if not self._guard():
            return
        if not messagebox.askyesno(
            "登入 1688",
            "即將開啟瀏覽器讓你登入 1688。\n登入成功後會自動存 cookie。\n\n繼續嗎？"):
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

    # ── ② 抓取 ──────────────────────────────
    def _on_scrape(self) -> None:
        if not self._guard():
            return
        if not COOKIE_PATH.exists():
            messagebox.showerror("錯誤", "還沒登入，請先按「🔑 登入 1688」")
            return
        products = self._read_products()
        if products is None:
            return
        item_ids = [p["item_id"] for p in products]
        self._save_state()
        self._busy(True, cancellable=True)
        self.cancel_event.clear()
        self._log(f"開始抓取 {len(item_ids)} 個商品…")
        threading.Thread(target=self._scrape_worker, args=(item_ids,), daemon=True).start()

    def _scrape_worker(self, item_ids: list[str]) -> None:
        from scraper.playwright_scraper import scrape_many
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(scrape_many(
                item_ids, cookie_path=COOKIE_PATH, out_dir=Path(OUTPUT_DIR),
                headless=False, progress_cb=self._thread_log,
                cancel_check=self.cancel_event.is_set,
            ))
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
        if messagebox.askyesno(
            "可能被擋 / cookie 過期",
            "有商品抓到 0 主圖（cookie 可能過期或被反爬擋）。\n要現在重新登入嗎？"):
            self._on_login()

    # ── ③ 執行 ──────────────────────────────
    def _on_run(self) -> None:
        if not self._guard():
            return
        products = self._read_products()
        if products is None:
            return
        # 缺 JSON 檢查：提醒先抓取
        missing = [p["code"] for p in products
                   if not (Path(OUTPUT_DIR) / f"{p['item_id']}.json").exists()
                   and not (Path(OUTPUT_DIR) / p["item_id"] / f"{p['item_id']}.json").exists()]
        if missing:
            if not messagebox.askyesno(
                "缺抓取資料",
                f"以下編號還沒抓取（缺 JSON）：\n{', '.join(missing)}\n\n"
                "缺的會被跳過。要繼續嗎？（建議先按「🔍 抓取商品」）"):
                return
        self._save_state()
        self._busy(True)
        self._log(f"開始產出 Excel（{len(products)} 個商品，影片={'開' if self.make_video.get() else '關'}）…")
        threading.Thread(target=self._run_worker, args=(products,), daemon=True).start()

    def _run_worker(self, products: list[dict]) -> None:
        from scraper.batch_pipeline2 import run_batch_two_tier
        try:
            res = run_batch_two_tier(
                json_dir=Path(OUTPUT_DIR),
                make_video=self.make_video.get(),
                products=products,
            )
            self._thread_log(
                f"✅ 完成：{res['success']}/{res['total']} 成功，失敗 {res['failed']}")
            for m in res.get("products", []):
                vtag = " | 🎬" if m.get("video") else ""
                self._thread_log(f"    ✓ {m['code']}: {m['sku_count']} SKU{vtag} | {m['title'][:30]}")
            for f in res.get("failures", []):
                self._thread_log(f"    ✗ {f['code']}: {f['error']}")
            excel = res.get("excel_path")
            if excel:
                self._thread_log(f"📄 蝦皮 Excel：{excel}")
                self.root.after(0, self._prompt_open_excel, Path(excel))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._thread_log(f"執行錯誤：{e}")
        finally:
            self.root.after(0, self._on_task_done)

    def _prompt_open_excel(self, excel: Path) -> None:
        if messagebox.askyesno(
            "完成",
            f"蝦皮 Excel 已產出：\n{excel}\n\n要打開它所在的資料夾嗎？"):
            _open_path(excel.parent)

    # ── ④ 素材夾 ──────────────────────────────
    def _on_open_assets(self) -> None:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        _open_path(ASSETS_DIR)

    # ── 其他 ──────────────────────────────
    def _on_pick_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="選 AI 上架名單 CSV",
            initialdir=str((BASE_DIR / "input") if (BASE_DIR / "input").exists() else BASE_DIR),
            filetypes=[("CSV", "*.csv"), ("所有檔案", "*.*")],
        )
        if path:
            self.csv_path.set(path)
            self._save_state()

    def _on_stop(self) -> None:
        self.cancel_event.set()
        self.stop_btn.config(state="disabled")
        self._status("正在停止，等目前這筆處理完…")

    def _on_task_done(self) -> None:
        self._busy(False)
        self.cancel_event.clear()
        self._refresh_cookie_status()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
