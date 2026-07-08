"""Responses API 對話串接版：Turn1 送 V1.0+圖→GPT 規劃+生圖，後續帶 previous_response_id 串接逐張生。
Claude 零加工：只讀 md、收圖、送；續圖只給最中性的「下一張」訊號。"""
import base64
import io
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)
from openai import OpenAI
from PIL import Image

from scraper.gpt_image_generator import load_design_spec, _imgs, PERSONA_DIR, REFERENCE_DIR

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
item = "953732723854"
spec = load_design_spec()

# 新策略（最不失真）：只餵 1688 真實「細節圖」（乾淨模特圖 + 簡體面料/尺碼面板）→ 簡轉繁 + 1:1。
# 不放老闆娘、不放參考圖——不讓 AI 重畫商品，只動文字與版型。
paths = sorted(Path(f"output/{item}/images/detail").glob("*.*"))


def uri(p):
    im = Image.open(p).convert("RGB")
    m = max(im.size)
    if m > 1024:
        s = 1024 / m
        im = im.resize((int(im.width * s), int(im.height * s)))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


content = [{"type": "input_text", "text": spec}] + \
          [{"type": "input_image", "image_url": uri(p)} for p in paths]
MODEL_IMG = "gpt-image-1.5"  # ← 畫圖層模型（預設 gpt-image-1）；導演層仍是 gpt-5.5
QUALITY = "low"              # ← 本輪測 gpt-image-1.5 Low
tools = [{"type": "image_generation", "model": MODEL_IMG, "size": "1024x1024", "quality": QUALITY}]
outdir = Path(f"output/{item}/images/photoeng_{MODEL_IMG.replace('.', '')}_{QUALITY}")
outdir.mkdir(parents=True, exist_ok=True)

# ── 費率（美金/1M token；gpt-image-1 每張）——請以 OpenAI 官方定價校正 ──
RATE_IN = 1.25       # gpt-5.5 input 未快取（估，待校正）
RATE_IN_CACHED = 0.125  # gpt-5.5 input 已快取（估 ~10%，待校正）
RATE_OUT = 10.0      # gpt-5.5 output（估，待校正）
RATE_IMG = 0.009     # gpt-image-1.5 1024² low 每張（估：272 tok × $32/1M；待用量校正）

count = 0
tok_in = tok_out = tok_cached = tok_reason = 0
turn_rows = []  # 每輪 (turn, in, cached, out, reason, imgs)


def save_imgs(resp):
    global count
    n = 0
    for o in resp.output:
        if getattr(o, "type", "") == "image_generation_call" and getattr(o, "result", None):
            count += 1
            n += 1
            dst = outdir / f"L_{count:02d}.png"
            dst.write_bytes(base64.b64decode(o.result))
            print(f"  存 {dst.name}")
    return n


def add_usage(resp, turn, imgs):
    """累加並記錄本輪用量；拆出 cached_tokens（快取有沒有生效的關鍵）與 reasoning_tokens。"""
    global tok_in, tok_out, tok_cached, tok_reason
    u = getattr(resp, "usage", None)
    if not u:
        return
    ti = getattr(u, "input_tokens", 0) or 0
    to = getattr(u, "output_tokens", 0) or 0
    idet = getattr(u, "input_tokens_details", None)
    tc = (getattr(idet, "cached_tokens", 0) or 0) if idet else 0
    odet = getattr(u, "output_tokens_details", None)
    tr = (getattr(odet, "reasoning_tokens", 0) or 0) if odet else 0
    tok_in += ti; tok_out += to; tok_cached += tc; tok_reason += tr
    turn_rows.append((turn, ti, tc, to, tr, imgs))
    print(f"  [用量] in {ti:,}（快取 {tc:,}={tc/ti*100 if ti else 0:.0f}%）| out {to:,}（推理 {tr:,}）| 圖 {imgs}")


print(f"送 {len(paths)} 張圖 + spec {len(spec)} 字 | 畫圖={MODEL_IMG} 品質={QUALITY}")
print("Turn 1：GPT 分析 + 規劃整套 + 生圖…")
t0 = time.time(); t_prev = t0
resp = client.responses.create(model="gpt-5.5",
                               input=[{"role": "user", "content": content}], tools=tools)
prev = resp.id
n1 = save_imgs(resp); add_usage(resp, 1, n1)
dt = time.time() - t_prev; t_prev = time.time()
print(f"  ⏱ Turn 1 耗時 {dt:.0f}s")
print("  規劃/回應：", (getattr(resp, "output_text", "") or "")[:400])

TARGET = 9  # spec 指定的張數
zeros = 0
for turn in range(2, 20):
    if count >= TARGET:
        break
    resp = client.responses.create(
        model="gpt-5.5",
        input=(f"你正在依照規範產出一整套共 {TARGET} 張商品圖，目前已完成 {count} 張。"
               f"請產出下一張（第 {count + 1} 張）。"
               f"務必產出圖片，不要只回文字。只有在 {TARGET} 張全部完成後才回覆 COMPLETE，不要提早停。"),
        previous_response_id=prev, tools=tools)
    prev = resp.id
    got = save_imgs(resp); add_usage(resp, turn, got)
    dt = time.time() - t_prev; t_prev = time.time()
    txt = (getattr(resp, "output_text", "") or "")
    print(f"Turn {turn}: 生圖 {got} 張 | ⏱ {dt:.0f}s | 回應 {txt[:80]}")
    if got == 0:
        zeros += 1
        print(f"  這輪沒生圖（連續 {zeros} 次）")
        if zeros >= 2:
            print("  連續兩次沒生圖 → 停")
            break
    else:
        zeros = 0
elapsed = time.time() - t0

# ── 成本拆解：未快取 input 付全價、已快取 input 付折扣價 ──
tok_in_full = tok_in - tok_cached
cost_in = tok_in_full/1e6*RATE_IN + tok_cached/1e6*RATE_IN_CACHED
cost_out = tok_out/1e6*RATE_OUT
cost_img = count*RATE_IMG
cost = cost_in + cost_out + cost_img
print(f"\n完成，共 {count} 張，位於 {outdir}")
print("── 每輪用量 ──  turn | input | cached | output | reason | imgs")
for t, ti, tc, to, tr, im in turn_rows:
    print(f"   T{t:<2} {ti:>8,} {tc:>8,} {to:>8,} {tr:>8,} {im:>4}")
print(f"── 總量 ── input {tok_in:,}（其中快取 {tok_cached:,} = {tok_cached/tok_in*100 if tok_in else 0:.0f}%）"
      f"/ output {tok_out:,}（推理 {tok_reason:,}）/ 圖 {count} 張")
print(f"── 成本拆解 ── input US${cost_in:.3f}（未快取 {tok_in_full:,} + 快取 {tok_cached:,}）"
      f"| output US${cost_out:.3f} | 圖 US${cost_img:.3f}")
print(f"── 合計 ── US${cost:.3f}（≈ NT${cost*32:.0f}）｜品質={QUALITY}")
print(f"── 總耗時 ── {elapsed:.0f}s（{elapsed/60:.1f} 分）/ {count} 張 = 每張 {elapsed/count if count else 0:.0f}s")
