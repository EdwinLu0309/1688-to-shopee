"""Responses API 對話串接版：Turn1 送 V1.0+圖→GPT 規劃+生圖，後續帶 previous_response_id 串接逐張生。
Claude 零加工：只讀 md、收圖、送；續圖只給最中性的「下一張」訊號。"""
import base64
import io
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)
from openai import OpenAI
from PIL import Image

from scraper.gpt_image_generator import load_design_spec, _imgs, PERSONA_DIR, REFERENCE_DIR

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
item = "953732723854"
spec = load_design_spec()

mains = sorted(Path(f"output/{item}/images/main").glob("*.*"))[:6]
skus = [Path(f"output/{item}/images/sku/sku_00{i}.jpg") for i in range(4)]
persona = _imgs(PERSONA_DIR, 2)
ref = _imgs(REFERENCE_DIR, 3)
paths = mains + skus + persona + ref


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
tools = [{"type": "image_generation", "size": "1024x1024", "quality": "high"}]
outdir = Path(f"output/{item}/images/listing_set")
outdir.mkdir(parents=True, exist_ok=True)

# ── 費率（美金/1M token；gpt-image-1 每張）——請以 OpenAI 官方定價校正 ──
RATE_IN = 1.25       # gpt-5.5 input（估，待校正）
RATE_OUT = 10.0      # gpt-5.5 output（估，待校正）
RATE_IMG = 0.167     # gpt-image-1 1024² high 每張（估，待校正）

count = 0
tok_in = tok_out = 0


def save_imgs(resp):
    global count
    for o in resp.output:
        if getattr(o, "type", "") == "image_generation_call" and getattr(o, "result", None):
            count += 1
            dst = outdir / f"L_{count:02d}.png"
            dst.write_bytes(base64.b64decode(o.result))
            print(f"  存 {dst.name}")


def add_usage(resp):
    global tok_in, tok_out
    u = getattr(resp, "usage", None)
    if u:
        tok_in += getattr(u, "input_tokens", 0) or 0
        tok_out += getattr(u, "output_tokens", 0) or 0


print(f"送 {len(paths)} 張圖 + V1.0 spec {len(spec)} 字")
print("Turn 1：GPT 分析 + 規劃整套 + 生圖…")
resp = client.responses.create(model="gpt-5.5",
                               input=[{"role": "user", "content": content}], tools=tools)
prev = resp.id
save_imgs(resp); add_usage(resp)
print("  規劃/回應：", (getattr(resp, "output_text", "") or "")[:400])

for turn in range(2, 14):
    if count >= 12:
        break
    resp = client.responses.create(
        model="gpt-5.5",
        input="繼續：產出你規劃中的下一張賣場圖。若整套已全部完成，只回覆 COMPLETE，不要再生圖。",
        previous_response_id=prev, tools=tools)
    prev = resp.id
    before = count
    save_imgs(resp); add_usage(resp)
    txt = (getattr(resp, "output_text", "") or "")
    got = count - before
    print(f"Turn {turn}: 生圖 {got} 張 | 回應 {txt[:80]}")
    if got == 0:
        print("  這輪沒生圖 → 視為整套完成，停")
        break

cost = tok_in/1e6*RATE_IN + tok_out/1e6*RATE_OUT + count*RATE_IMG
print(f"完成，共 {count} 張，位於 {outdir}")
print(f"── 用量 ── input {tok_in:,} tok / output {tok_out:,} tok / 圖 {count} 張")
print(f"── 估算花費 ── US${cost:.3f}（≈ NT${cost*32:.0f}）｜費率待官方校正")
