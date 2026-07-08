"""1688 細節圖 → 蝦皮 1:1 繁體版：per-image 轉換（轉蝦皮版 V1）。
每張細節圖獨立一次 image_generation：保留原照片、簡轉繁、移除英文裝飾字、補成 1:1。
先測代表性 3 張（乾淨無字 / 圖+簡體疊字 / 純簡體面板）驗證「保留原圖」可行，再全 23 張。"""
import base64
import io
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)
from openai import OpenAI
from PIL import Image

from scraper.gpt_image_generator import load_design_spec

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
item = "953732723854"
spec = load_design_spec()  # 「轉蝦皮版 V1」md（含各項規則 + 簡轉繁範例）

# V2 System Prompt（釘在 instructions）：重點＝別縮小加白邊，改成智慧裁背景+延伸背景填滿畫面
SYSTEM = ("Reframe the uploaded product photo into a 1:1 square for Taiwan Shopee. Do NOT treat "
          "'preserve the whole image' as the top priority. Priority order: (1) product "
          "authenticity — never alter garment, fabric, color, wrinkles, sheen, pose, model, "
          "face, or body; (2) make the PRODUCT AS LARGE AS POSSIBLE in frame; (3) full body "
          "visible; (4) person centered (<=5% offset); (5) 1:1 ratio; (6) keep background. "
          "To fill the square, FIRST enlarge the product/subject, THEN extend the existing "
          "background (same wall, floor, color temperature, lighting) via smart-crop of ceiling/"
          "floor/side walls. NEVER shrink the whole image to fit 1:1, and NEVER add plain white "
          "or polaroid borders. Target: person ~82-88% of frame height, garment ~75-85%, feet "
          "2-4% from bottom, head 3-5% from top. Replace Simplified Chinese with Traditional "
          "Chinese; remove English-only decorative text. Never crop the product (hem, waistband, "
          "body). LOCK COLORS EXACTLY to the source: a grey garment must stay neutral grey and "
          "must NOT shift toward blue or navy; never deepen, saturate, or recolor any garment. "
          "Output must look like a real reframed photo, not AI-generated.")

MODEL_IMG = "gpt-image-1.5"  # 強模型 + low：無文字圖測能否保真又省 4 倍
QUALITY = "low"
# 每張估價（1024²）= 固定 token(low272/med1056/high4160) × 各模型 output 費率
_RATES = {
    "gpt-image-1": {"low": 0.011, "medium": 0.042, "high": 0.167},
    "gpt-image-1.5": {"low": 0.009, "medium": 0.034, "high": 0.133},
    "gpt-image-1-mini": {"low": 0.002, "medium": 0.008, "high": 0.033},
}
RATE_IMG = _RATES[MODEL_IMG][QUALITY]

detail_dir = Path(f"output/{item}/images/detail")
# V2 STEP1 評分後只留全身★★★★☆+（= Edwin 9 宮格那批）；半身/腿部/面板不轉。
FULLBODY = ["detail_011", "detail_012", "detail_013", "detail_014", "detail_016",
            "detail_017", "detail_019", "detail_020", "detail_022"]
if len(sys.argv) > 1 and sys.argv[1] == "all":
    srcs = sorted(detail_dir.glob("*.*"))
else:
    srcs = [detail_dir / f"{n}.jpg" for n in FULLBODY]

outdir = Path(f"output/{item}/images/shopee_1to1_v2_{MODEL_IMG.replace('.', '')}_{QUALITY}_lock")
outdir.mkdir(parents=True, exist_ok=True)
tools = [{"type": "image_generation", "model": MODEL_IMG, "size": "1024x1024", "quality": QUALITY}]

INSTR = ("請把以下這張 1688 模特圖轉成一張 1:1 蝦皮商品圖："
         "用智慧裁切裁掉多餘背景（天花板/地板/左右牆）＋延伸原背景，"
         "讓人物填滿約 82-88% 畫面高度、水平置中——"
         "絕對不要整張縮小、不要加白邊。簡體改繁體、刪除純英文字。"
         "商品/模特/布料/顏色/姿勢 100% 保留，不要重畫。"
         "⚠️ 嚴格鎖定原色：灰色必須維持原本的中性灰、絕對不可偏藍或變深藍，"
         "其他顏色也一律照原圖、不得偏移或加深。")


def uri(p):
    im = Image.open(p).convert("RGB")
    m = max(im.size)
    if m > 1024:
        s = 1024 / m
        im = im.resize((int(im.width * s), int(im.height * s)))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


print(f"轉換 {len(srcs)} 張 | 畫圖={MODEL_IMG} 品質={QUALITY} | spec {len(spec)} 字")
tok_in = tok_out = 0
t0 = time.time()
for i, src in enumerate(srcs, 1):
    content = [{"type": "input_text", "text": spec + "\n\n" + INSTR},
               {"type": "input_image", "image_url": uri(src)}]
    t = time.time()
    resp = client.responses.create(model="gpt-5.5", instructions=SYSTEM,
                                   input=[{"role": "user", "content": content}], tools=tools)
    dt = time.time() - t
    imgs = [o for o in resp.output
            if getattr(o, "type", "") == "image_generation_call" and getattr(o, "result", None)]
    if imgs:
        dst = outdir / f"{src.stem}_1to1.png"
        dst.write_bytes(base64.b64decode(imgs[0].result))
        print(f"{i}/{len(srcs)} {src.name} → {dst.name} | ⏱{dt:.0f}s")
    else:
        print(f"{i}/{len(srcs)} {src.name} ✗ 沒生圖：{(getattr(resp, 'output_text', '') or '')[:120]}")
    u = getattr(resp, "usage", None)
    if u:
        tok_in += getattr(u, "input_tokens", 0) or 0
        tok_out += getattr(u, "output_tokens", 0) or 0
elapsed = time.time() - t0
cost = tok_in / 1e6 * 1.25 + tok_out / 1e6 * 10 + len(srcs) * RATE_IMG
print(f"── {len(srcs)} 張 | in {tok_in:,} / out {tok_out:,} tok | 圖 ${RATE_IMG}/張 "
      f"| 估 US${cost:.3f}（NT${cost*32:.0f}）| {elapsed:.0f}s（每張 {elapsed/len(srcs):.0f}s）")
print(f"位於 {outdir}")
