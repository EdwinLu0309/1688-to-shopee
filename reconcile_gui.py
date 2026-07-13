"""1688 訂單刷新（金流核對）— 獨立 GUI（不動 gui.py / order_gui.py）。

取代舊手動流程「1688 待付款 → 匯出訂單報表 → 丟資料夾 → 匯入 1688_DB」。
按一下就去 1688 撈當下待付款訂單（下單日 >= 指定日）→ 覆蓋核對表 1688_DB，
各日期核對分頁靠「卖家公司名（廠商）」自動帶入；廠商若改價，實付款會一起覆蓋更新。

流程：設核對日期 →
  🔄 刷新預覽（dry-run：開瀏覽器抓訂單、顯示筆數/實付合計/廠商，不寫）
  ✅ 寫入 1688_DB（把剛預覽的訂單覆蓋進 DB）

執行緒模型仿 order_gui.py：worker thread 跑 refresh()，root.after(0,…) 回主緒更新 UI。
需要 1688 cookie（config/cookies.json；用主 gui.py 的「🔑 登入 1688」產生）。
"""
import sys
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import settings  # noqa: E402  （早匯入：Windows UTF-8 修正）
from scraper.ordering.reconcile_pipeline import (  # noqa: E402
    RefreshResult, format_preview, refresh,
)

STATUS_OPTIONS = {
    "待付款（代付款，預設）": "waitbuyerpay",
    "近期全部（待付款+待發貨+待收貨）": "all",
    "待發貨": "waitsellersend",
    "待收貨": "waitbuyerreceive",
}


class ReconcileApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("1688 訂單刷新（金流核對）")
        self.BG, self.FG = "#f5f5f5", "#222222"
        try:
            root.tk_setPalette(background=self.BG, foreground=self.FG)
        except tk.TclError:
            pass
        root.configure(bg=self.BG)
        root.geometry("780x660")

        self._busy = False
        self._last: RefreshResult | None = None

        F_TITLE = ("Helvetica", 20, "bold")
        F_LBL = ("Helvetica", 14)
        F_BTN = ("Helvetica", 15, "bold")
        BG, FG = self.BG, self.FG

        tk.Label(root, text="💰 1688 訂單刷新（金流核對）", font=F_TITLE, bg=BG, fg=FG).pack(pady=(14, 2))
        tk.Label(root, text="抓當下 1688 訂單 → 覆蓋核對表 1688_DB（廠商改價一起更新）",
                 font=("Helvetica", 12), bg=BG, fg="#666666").pack(pady=(0, 8))

        form = tk.Frame(root, bg=BG)
        form.pack(fill="x", padx=16)

        row1 = tk.Frame(form, bg=BG)
        row1.pack(fill="x", pady=4)
        tk.Label(row1, text="核對日期", font=F_LBL, bg=BG, fg=FG, width=10, anchor="w").pack(side="left")
        self.date_var = tk.StringVar(value=date.today().isoformat())
        tk.Entry(row1, textvariable=self.date_var, font=F_LBL, bg="#ffffff", fg="#111111", width=14).pack(side="left")
        tk.Label(row1, text="（只抓下單日 >= 此日的訂單）", font=("Helvetica", 11), bg=BG, fg="#888888").pack(side="left", padx=6)

        row2 = tk.Frame(form, bg=BG)
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="訂單狀態", font=F_LBL, bg=BG, fg=FG, width=10, anchor="w").pack(side="left")
        self.status_var = tk.StringVar(value=list(STATUS_OPTIONS)[0])
        tk.OptionMenu(row2, self.status_var, *STATUS_OPTIONS).pack(side="left")

        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x", padx=16, pady=(10, 4))
        self.btn_login = tk.Button(btns, text="🔑 登入美甲帳號", font=F_BTN, command=self._on_login)
        self.btn_login.pack(side="left", padx=4)
        self.btn_preview = tk.Button(btns, text="🔄 刷新預覽", font=F_BTN, bg="#1a7f37", fg="#ffffff",
                                     command=self._on_preview)
        self.btn_preview.pack(side="left", padx=4)
        self.btn_commit = tk.Button(btns, text="✅ 寫入 1688_DB", font=F_BTN, command=self._on_commit, state="disabled")
        self.btn_commit.pack(side="left", padx=4)

        self.status_lbl = tk.StringVar(value="設核對日期 → 🔄 刷新預覽")
        tk.Label(root, textvariable=self.status_lbl, font=("Helvetica", 12), bg=BG, fg="#1a7f37",
                 anchor="w").pack(fill="x", padx=16, pady=(4, 2))

        self.log = tk.Text(root, height=20, font=("Menlo", 12), borderwidth=1,
                           bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4", state="disabled")
        self.log.pack(fill="both", expand=True, padx=16, pady=(4, 14))

    # ── helpers ──
    def _log(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _notify(self, msg: str):
        self.root.after(0, self._log, msg)

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_preview.config(state=state)
        self.btn_login.config(state=state)
        if busy:
            self.btn_commit.config(state="disabled")
        elif self._last is not None and self._last.order_count > 0:
            self.btn_commit.config(state="normal")

    # ── 登入美甲帳號（存 cookies_nail.json）──
    def _on_login(self):
        if not self._guard():
            return
        self._set_busy(True)
        self.status_lbl.set("開瀏覽器登入美甲 1688 帳號…（登完會自動存檔）")
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self):
        try:
            import asyncio
            from scraper.playwright_scraper import save_cookies
            n = asyncio.run(save_cookies(settings.COOKIE_PATH_NAIL))
            self.root.after(0, self._log, f"✅ 美甲帳號已登入，存 {n} 個 cookie → cookies_nail.json")
            self.root.after(0, self._status_msg, "美甲帳號登入完成 → 可按「🔄 刷新預覽」")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 登入失敗：{e}")
            self.root.after(0, self._status_msg, "登入失敗")
        finally:
            self.root.after(0, self._set_busy, False)

    def _guard(self) -> bool:
        if self._busy:
            messagebox.showinfo("請稍候", "上一個動作還在執行")
            return False
        return True

    # ── 刷新預覽（dry-run）──
    def _on_preview(self):
        if not self._guard():
            return
        if not Path(settings.COOKIE_PATH_NAIL).exists():
            messagebox.showwarning("缺 cookie", "找不到 cookies_nail.json\n請先按左邊「🔑 登入美甲帳號」")
            return
        self._set_busy(True)
        self._last = None
        self.btn_commit.config(state="disabled")
        self.status_lbl.set("刷新中…（看瀏覽器；若跳驗證碼請手動解）")
        threading.Thread(target=self._preview_worker,
                         args=(self.date_var.get().strip(), STATUS_OPTIONS[self.status_var.get()]),
                         daemon=True).start()

    def _preview_worker(self, the_date, status):
        try:
            result = refresh(since_date=the_date, status=status, commit=False, callback=self._notify)
            self._last = result
            self.root.after(0, self._log, "\n" + format_preview(result))
            if result.order_count == 0:
                self.root.after(0, self._status_msg, "0 筆訂單 → 不寫入（避免清空 DB）")
            else:
                self.root.after(0, self._status_msg,
                                f"預覽 {result.order_count} 筆／實付¥{result.total_actual_pay:,.2f} → 確認後按「✅ 寫入 1688_DB」")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 刷新失敗：{e}")
            self.root.after(0, self._status_msg, "刷新失敗")
            self._last = None
        finally:
            self.root.after(0, self._set_busy, False)

    def _status_msg(self, msg):
        self.status_lbl.set(msg)

    # ── 寫入 1688_DB ──
    def _on_commit(self):
        if not self._guard() or not self._last or self._last.order_count == 0:
            return
        n = self._last.order_count
        if not messagebox.askyesno(
            "覆蓋確認",
            f"把這 {n} 筆訂單覆蓋寫進核對表的 1688_DB？\n（會清掉 1688_DB 現有資料後重寫，各核對分頁自動更新）"):
            return
        self._set_busy(True)
        self.btn_commit.config(state="disabled")
        self.status_lbl.set("寫入 1688_DB 中…")
        threading.Thread(target=self._commit_worker, daemon=True).start()

    def _commit_worker(self):
        try:
            from scraper.ordering.reconcile_db import ReconcileDB
            src = f"1688刷新 {self._last.status or '全部'} 自{self._last.since_date or '全部'}"
            info = ReconcileDB().overwrite(self._last.records, source_name=src)
            self.root.after(0, self._log,
                            f"✅ 已覆蓋 1688_DB：{info['orders']} 訂單／{info['rows']} 列（{info['updated_time']}）")
            self.root.after(0, self._status_msg, "已寫入 1688_DB → 回 Google Sheet 核對")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 寫入失敗：{e}")
            self.root.after(0, self._status_msg, "寫入失敗")
        finally:
            self.root.after(0, self._set_busy, False)


def main():
    root = tk.Tk()
    ReconcileApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
