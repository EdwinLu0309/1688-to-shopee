"""AI 店長顧問（#S104 Point 2）——每天一則白話，讀完三家數據給結論+待辦。

Edwin 定調：AI 是「幫我省時間、條列重點、做人類短期做不到的事」的工具，
不是做完善 dashboard。所以這裡把三家的關鍵數 + 跨表訊號壓成 digest → Claude
用「專業電商店長顧問」身份回四塊白話：
  今天一句話 / ✅ 好的維持 / ⚠️ 不 OK 要動作 / 🔎 可操作空間

無 ANTHROPIC_API_KEY 或呼叫失敗 → 退回 rule-based 摘要（照樣有東西看，不開天窗）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime

from loguru import logger

from .metrics import DailyReport, METRICS, fmt_delta, fmt_value
from .sheet_util import ensure_ws
from .signals import ShopSignals

MODEL = "claude-sonnet-4-6"   # 與 copywriter 同款；要換模型改這裡
TAB = "AI店長顧問"

SYSTEM_PROMPT = """你是 Edwin 蝦皮三賣場（美甲 nail／女裝 lady／嬰幼 baby）的專業電商店長顧問。
Edwin 是多棲經營者、時間有限，他請你每天早上「替他讀完三家昨天的數據，直接給結論和待辦」。

你的價值在「跨表交叉」——把商品、廣告、大盤放一起，講出他單看一張表看不出的話。
例如：CTR 升但轉換降＝詳情/價格問題不是曝光問題；廣告 ROAS 掉但營收沒掉＝自然流量補上可縮廣告；
某關鍵字燒錢零轉換＝加否定詞；某關鍵字 ROAS 高＝加碼。

鐵律：
- 少而精。只講真正觸發決策的幾件事，不要逐項複述數字。寧可短。
- 具體、可執行、講到「哪個賣場、哪個商品/關鍵字、做什麼動作」。不要空話（如「持續優化」）。
- 用繁體中文、台灣電商口吻。金額是新台幣。
- 領先指標（CTR/加購/轉換）3-7 天可判讀；落後指標（營收/排名）要拉長看，別看一天就下結論。
- 沒有值得講的就少講，不要硬湊。

只回 JSON（不要 markdown 圍欄），格式：
{
  "one_liner": "今天一句話總結三家狀況（≤40字）",
  "keep_good": ["✅ 表現好、維持就好的點（0-3 條，可空）"],
  "action_needed": ["⚠️ 不 OK、今天該做的具體動作（0-4 條）"],
  "opportunity": ["🔎 可操作的空間/機會（0-3 條）"]
}"""


@dataclass
class Advice:
    one_liner: str = ""
    keep_good: list[str] = field(default_factory=list)
    action_needed: list[str] = field(default_factory=list)
    opportunity: list[str] = field(default_factory=list)
    source: str = "ai"   # ai / fallback


# ── digest：把數據壓成給 Claude 讀的精簡文字 ─────────────────────────

def build_digest(report: DailyReport, signals: list[ShopSignals]) -> str:
    lines = [f"資料日期：{report.dt.isoformat()}（昨天）", ""]
    sig_by_shop = {s.shop: s for s in signals}

    for sr in report.shops:
        if not sr.has_data:
            lines.append(f"【{sr.name}】無資料（當天沒抓到或未登入）")
            lines.append("")
            continue
        lines.append(f"【{sr.name}】")
        # 8 關鍵數（值 + 昨比 + 週比）
        for m in METRICS:
            cell = sr.cells.get(m.key)
            if cell is None or cell.value is None:
                continue
            lines.append(
                f"- {m.label}：{fmt_value(cell.value, m.kind)}"
                f"（昨{fmt_delta(cell.dod, m.direction)} 週{fmt_delta(cell.wow, m.direction)}）"
            )
        # 跨表訊號
        sig = sig_by_shop.get(sr.shop)
        if sig:
            if sig.flags:
                lines.append("  大盤警示：" + "；".join(sig.flags))
            if sig.surges:
                s = "、".join(f"{x['name']}(訂單{int(x['orders'])}"
                              + (f" vs 日均{x['avg7']}" if x['avg7'] else " 新爆") + ")"
                              for x in sig.surges[:3])
                lines.append(f"  🔺銷量爆發：{s}")
            if sig.dead_views:
                s = "、".join(f"{x['name']}(訪客{int(x['uv'] or 0)}、0 成交)" for x in sig.dead_views[:3])
                lines.append(f"  👀有看沒買：{s}")
            if sig.kw_waste:
                s = "、".join(f"{x['keyword']}(燒${x['cost']}、0 轉換)" for x in sig.kw_waste[:3])
                lines.append(f"  💸關鍵字燒錢零轉換：{s}")
            if sig.kw_wins:
                s = "、".join(f"{x['keyword']}(ROAS {x['roas']}、花${x['cost']})" for x in sig.kw_wins[:3])
                lines.append(f"  ⭐高ROAS關鍵字：{s}")
            if sig.gms_wins:
                s = "、".join(f"{x['name']}(ROAS {x['roas']})" for x in sig.gms_wins[:3])
                lines.append(f"  ⭐自動選品高ROAS商品：{s}")
        lines.append("")
    return "\n".join(lines)


# ── Claude 呼叫 ──────────────────────────────────────────────────────

def _strip_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
        t = t.removeprefix("json").strip()
    return t


def generate_advice(digest: str) -> Advice:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("缺 ANTHROPIC_API_KEY → 顧問走 rule-based fallback")
        return _fallback(digest)
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"以下是昨天三賣場數據，請給今天的店長建議：\n\n{digest}"}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = json.loads(_strip_json(text))
        return Advice(
            one_liner=str(data.get("one_liner", "")).strip(),
            keep_good=[str(x) for x in (data.get("keep_good") or [])],
            action_needed=[str(x) for x in (data.get("action_needed") or [])],
            opportunity=[str(x) for x in (data.get("opportunity") or [])],
            source="ai",
        )
    except Exception as e:  # noqa: BLE001 顧問掛不該擋掉整個分析層
        logger.warning(f"AI 顧問生成失敗，改 fallback：{e}")
        return _fallback(digest)


def _fallback(digest: str) -> Advice:
    """無 AI 時的規則版：把已抽好的訊號直接條列（照樣有結論可看）。"""
    adv = Advice(source="fallback")
    adv.one_liner = "（未接 AI，以下為規則版重點）見 ⚠️/🔎 條列。"
    # 從 digest 撈已標記的行
    for line in digest.splitlines():
        s = line.strip()
        if s.startswith("💸") or s.startswith("👀") or "警示" in s:
            adv.action_needed.append(s)
        elif s.startswith("⭐") or s.startswith("🔺"):
            adv.opportunity.append(s)
    if not adv.action_needed:
        adv.action_needed.append("昨天沒有踩到警戒門檻的項目。")
    return adv


# ── 寫進 Sheet ──────────────────────────────────────────────────────

def _join(items: list[str]) -> str:
    return "\n".join(items) if items else "—"


def write_advisor(sh, day: date, advice: Advice) -> None:
    header = ["資料日期", "今天一句話", "✅ 好的維持", "⚠️ 要動作", "🔎 可操作空間", "來源", "產生時間"]
    ws = ensure_ws(sh, TAB, rows=400, cols=len(header))
    existing = ws.get_values("A1")
    if not existing:
        ws.update(values=[header], range_name="A1", raw=True)
    row = [
        day.isoformat(),
        advice.one_liner,
        _join(advice.keep_good),
        _join(advice.action_needed),
        _join(advice.opportunity),
        "AI" if advice.source == "ai" else "規則版",
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    ]
    # 冪等：同資料日期已有 → 覆蓋那列；否則插在最上面（最新在上，開頁即見今天）
    dates = ws.col_values(1)
    if day.isoformat() in dates[1:]:
        idx = dates.index(day.isoformat()) + 1
        ws.update(values=[row], range_name=f"A{idx}", raw=True)
    else:
        ws.insert_row(row, index=2, value_input_option="RAW")
    logger.info(f"AI 店長顧問已寫入（{day}，來源={advice.source}）")
