"""每日訂貨小幫手 — 獨立 GUI（不動主上架 gui.py）。

流程：選蝦皮匯出檔 + 密碼 + 日期 →
  📥 匯入預覽（dry-run，join 訂貨主檔過濾預購品、算今日訂貨總金額）
  ✅ 寫入 Sheet（明細+彙總寫進「【Lady】預購商品訂貨表」）
  🛒 下單（讀彙總 → 1688 加購物車 → 回寫下單狀態）
  🔍 核對（比對購物車商品/規格/數量）

執行緒模型仿 gui.py：worker thread 跑 asyncio，root.after(0,…) 回主緒更新 UI。
下單/核對要 1688 cookie（config/cookies.json；用主 gui.py 的「🔑 登入 1688」產生）。
"""
import asyncio
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox

BASE_DIR = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(BASE_DIR))

from config import settings  # noqa: E402  （早匯入：Windows UTF-8 修正）
from scraper.ordering.order_sheet import OrderSheet  # noqa: E402
from scraper.ordering.pipeline import format_report, import_orders  # noqa: E402


class OrderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("每日訂貨小幫手")
        self.BG, self.FG = "#f5f5f5", "#222222"
        try:
            root.tk_setPalette(background=self.BG, foreground=self.FG)
        except tk.TclError:
            pass
        root.configure(bg=self.BG)
        root.geometry("760x680")

        self._busy = False
        self._last_result = None  # 上次 dry-run 結果（供「寫入」用）

        F_TITLE = ("Helvetica", 20, "bold")
        F_LBL = ("Helvetica", 14)
        F_BTN = ("Helvetica", 15, "bold")
        BG, FG = self.BG, self.FG

        tk.Label(root, text="🛒 每日訂貨小幫手", font=F_TITLE, bg=BG, fg=FG).pack(pady=(14, 6))

        # ── 輸入區 ──
        form = tk.Frame(root, bg=BG)
        form.pack(fill="x", padx=16)

        # 匯出檔
        row1 = tk.Frame(form, bg=BG)
        row1.pack(fill="x", pady=3)
        tk.Label(row1, text="蝦皮匯出檔", font=F_LBL, bg=BG, fg=FG, width=10, anchor="w").pack(side="left")
        self.file_var = tk.StringVar()
        tk.Entry(row1, textvariable=self.file_var, font=F_LBL, bg="#ffffff", fg="#111111").pack(
            side="left", fill="x", expand=True, padx=4)
        tk.Button(row1, text="選檔…", font=F_LBL, command=self._pick_file).pack(side="left")

        # 密碼 + 日期
        row2 = tk.Frame(form, bg=BG)
        row2.pack(fill="x", pady=3)
        tk.Label(row2, text="密碼", font=F_LBL, bg=BG, fg=FG, width=10, anchor="w").pack(side="left")
        self.pw_var = tk.StringVar()
        tk.Entry(row2, textvariable=self.pw_var, font=F_LBL, bg="#ffffff", fg="#111111", width=12).pack(side="left", padx=4)
        tk.Label(row2, text="訂貨日期", font=F_LBL, bg=BG, fg=FG).pack(side="left", padx=(16, 4))
        self.date_var = tk.StringVar(value=date.today().isoformat())
        tk.Entry(row2, textvariable=self.date_var, font=F_LBL, bg="#ffffff", fg="#111111", width=14).pack(side="left")

        # ── 動作按鈕 ──
        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x", padx=16, pady=(10, 4))
        self.btn_preview = tk.Button(btns, text="📥 匯入預覽", font=F_BTN, bg="#1a7f37", fg="#ffffff",
                                     command=self._on_preview)
        self.btn_preview.pack(side="left", padx=4)
        self.btn_commit = tk.Button(btns, text="✅ 寫入 Sheet", font=F_BTN, command=self._on_commit, state="disabled")
        self.btn_commit.pack(side="left", padx=4)
        self.btn_place = tk.Button(btns, text="🛒 下單", font=F_BTN, command=self._on_place)
        self.btn_place.pack(side="left", padx=4)
        self.btn_verify = tk.Button(btns, text="🔍 核對", font=F_BTN, command=self._on_verify)
        self.btn_verify.pack(side="left", padx=4)

        # ── 狀態列 ──
        self.status_var = tk.StringVar(value="選匯出檔 → 匯入預覽")
        tk.Label(root, textvariable=self.status_var, font=("Helvetica", 12), bg=BG, fg="#1a7f37",
                 anchor="w").pack(fill="x", padx=16, pady=(4, 2))

        # ── log ──
        self.log = tk.Text(root, height=22, font=("Menlo", 12), borderwidth=1,
                           bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4", state="disabled")
        self.log.pack(fill="both", expand=True, padx=16, pady=(4, 14))

    # ── UI helpers ──
    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="選蝦皮待出貨匯出檔",
            filetypes=[("Excel", "*.xlsx"), ("All", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def _log(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _status(self, msg: str):
        self.status_var.set(msg)

    def _notify(self, msg: str):
        self.root.after(0, self._log, msg)

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_preview, self.btn_place, self.btn_verify):
            b.config(state=state)
        if not busy and self._last_result is not None:
            self.btn_commit.config(state="normal")

    def _guard(self) -> bool:
        if self._busy:
            messagebox.showinfo("請稍候", "上一個動作還在執行")
            return False
        return True

    # ── 匯入預覽（dry-run）──
    def _on_preview(self):
        if not self._guard():
            return
        path = self.file_var.get().strip()
        if not path or not Path(path).exists():
            messagebox.showwarning("缺檔案", "請先選蝦皮匯出檔")
            return
        self._set_busy(True)
        self.btn_commit.config(state="disabled")
        self._status("匯入預覽中…")
        threading.Thread(target=self._preview_worker,
                         args=(path, self.pw_var.get().strip(), self.date_var.get().strip()),
                         daemon=True).start()

    def _preview_worker(self, path, pw, the_date):
        try:
            result = import_orders(path, date=the_date, password=pw or None, commit=False)
            self._last_result = (path, pw, the_date)
            self.root.after(0, self._log, format_report(result, commit=False))
            self.root.after(0, self._status,
                            f"預覽完成：{len(result.summary_rows)} SKU，¥{result.total_cost_cny:,.2f} → 確認後按「✅ 寫入 Sheet」")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 匯入失敗：{e}")
            self.root.after(0, self._status, "匯入失敗")
            self._last_result = None
        finally:
            self.root.after(0, self._set_busy, False)

    # ── 寫入 Sheet（commit）──
    def _on_commit(self):
        if not self._guard() or not self._last_result:
            return
        path, pw, the_date = self._last_result
        if not messagebox.askyesno("寫入確認", f"把 {the_date} 的訂單明細+彙總寫進 Google Sheet？"):
            return
        self._set_busy(True)
        self.btn_commit.config(state="disabled")
        self._status("寫入 Sheet 中…")
        threading.Thread(target=self._commit_worker, args=(path, pw, the_date), daemon=True).start()

    def _commit_worker(self, path, pw, the_date):
        try:
            result = import_orders(path, date=the_date, password=pw or None, commit=True)
            self.root.after(0, self._log,
                            f"✅ 已寫入：明細 {result.detail_written} 列、彙總 {len(result.summary_rows)} SKU")
            self.root.after(0, self._status, "已寫入 Sheet → 可按「🛒 下單」")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 寫入失敗：{e}")
            self.root.after(0, self._status, "寫入失敗")
        finally:
            self.root.after(0, self._set_busy, False)

    # ── 下單 ──
    def _on_place(self):
        if not self._guard():
            return
        the_date = self.date_var.get().strip()
        if not messagebox.askyesno("下單確認", f"把 {the_date} 彙總裡「未下單」的 SKU 加進 1688 購物車？\n（會開瀏覽器，驗證碼需手動解）"):
            return
        self._set_busy(True)
        self._status("下單中…（看瀏覽器）")
        threading.Thread(target=self._place_worker, args=(the_date,), daemon=True).start()

    def _place_worker(self, the_date):
        try:
            from scraper.ordering.cart_order import run_place_orders
            result = run_place_orders(the_date, callback=self._notify, only_unordered=True)
            if not result:
                self.root.after(0, self._log, "（沒有待下單的項目；先寫入 Sheet 或全部已下單）")
            else:
                ok = sum(1 for s in result.values() if s.startswith("✅"))
                self.root.after(0, self._log, f"下單完成：{ok}/{len(result)} 成功")
            self.root.after(0, self._status, "下單結束 → 可按「🔍 核對」")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 下單失敗：{e}")
            self.root.after(0, self._status, "下單失敗")
        finally:
            self.root.after(0, self._set_busy, False)

    # ── 核對 ──
    def _on_verify(self):
        if not self._guard():
            return
        the_date = self.date_var.get().strip()
        self._set_busy(True)
        self._status("核對中…")
        threading.Thread(target=self._verify_worker, args=(the_date,), daemon=True).start()

    def _verify_worker(self, the_date):
        try:
            from scraper.ordering.cart_order import _read_summary_rows, build_order_items, verify_cart
            sheet = OrderSheet()
            master = sheet.load_master()
            rows = _read_summary_rows(sheet, the_date, only_unordered=False)
            items, _ = build_order_items(rows, master)
            if not items:
                self.root.after(0, self._log, "（該日沒有可核對的項目）")
                return
            statuses = asyncio.run(verify_cart(items, callback=self._notify))
            idx_to_sku = {it.row_index: it.sku_code for it in items}
            ok = sum(1 for s in statuses.values() if s.startswith("✅"))
            self.root.after(0, self._log, f"核對完成：{ok}/{len(statuses)} 正確")
            for idx, status in statuses.items():
                self.root.after(0, self._log, f"  {status}  {idx_to_sku.get(idx, idx)}")
            self.root.after(0, self._status, "核對結束")
        except Exception as e:
            self.root.after(0, self._log, f"❌ 核對失敗：{e}")
            self.root.after(0, self._status, "核對失敗")
        finally:
            self.root.after(0, self._set_busy, False)


def main():
    root = tk.Tk()
    OrderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
