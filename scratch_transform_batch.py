"""多商品批次：1688 細節圖 → 蝦皮 1:1 繁體版（gpt-image-1.5 low + 轉蝦皮版 V2 + 鎖色）。
每支只轉「全身乾淨模特圖」（人工分類挑出的 detail 檔），存 images/shopee_1to1_final/。"""
import base64
import io
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)
from openai import OpenAI
from PIL import Image

from scraper.gpt_image_generator import load_design_spec

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
spec = load_design_spec()

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

INSTR = ("請把以下這張 1688 模特圖轉成一張 1:1 蝦皮商品圖："
         "用智慧裁切裁掉多餘背景（天花板/地板/左右牆）＋延伸原背景，"
         "讓人物填滿約 82-88% 畫面高度、水平置中——絕對不要整張縮小、不要加白邊。"
         "簡體改繁體、刪除純英文字。商品/模特/布料/顏色/姿勢 100% 保留，不要重畫。"
         "⚠️ 嚴格鎖定原色：灰色必須維持原本的中性灰、絕對不可偏藍或變深藍，"
         "其他顏色也一律照原圖、不得偏移或加深。")

MODEL_IMG = "gpt-image-1.5"
QUALITY = "low"
tools = [{"type": "image_generation", "model": MODEL_IMG, "size": "1024x1024", "quality": QUALITY}]

# 人工分類挑出的「全身乾淨模特圖」（953… 已在 lock 資料夾，這裡跑其餘 4 支）
PICKS = {
    "940764393421": ["detail_016", "detail_017", "detail_019", "detail_020", "detail_021"],
    "816818820419": ["detail_012", "detail_014", "detail_015", "detail_016", "detail_020", "detail_021", "detail_023"],
    "962742217114": ["detail_007", "detail_008", "detail_009", "detail_011", "detail_012", "detail_014", "detail_015", "detail_016", "detail_019"],
    "925590172612": ["detail_012", "detail_014", "detail_015", "detail_016", "detail_020", "detail_021", "detail_023"],
}


def uri(p):
    im = Image.open(p).convert("RGB")
    m = max(im.size)
    if m > 1024:
        s = 1024 / m
        im = im.resize((int(im.width * s), int(im.height * s)))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


t0 = time.time()
total = 0
for item, stems in PICKS.items():
    outdir = Path(f"output/{item}/images/shopee_1to1_final")
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"=== {item} ({len(stems)} 張) ===")
    for stem in stems:
        src = Path(f"output/{item}/images/detail/{stem}.jpg")
        if not src.exists():
            print(f"  {stem} ✗ 無原圖")
            continue
        content = [{"type": "input_text", "text": spec + "\n\n" + INSTR},
                   {"type": "input_image", "image_url": uri(src)}]
        t = time.time()
        resp = client.responses.create(model="gpt-5.5", instructions=SYSTEM,
                                       input=[{"role": "user", "content": content}], tools=tools)
        imgs = [o for o in resp.output
                if getattr(o, "type", "") == "image_generation_call" and getattr(o, "result", None)]
        if imgs:
            dst = outdir / f"{stem}_1to1.png"
            dst.write_bytes(base64.b64decode(imgs[0].result))
            total += 1
            print(f"  {stem} → {dst.name} | ⏱{time.time()-t:.0f}s")
        else:
            print(f"  {stem} ✗ 沒生圖")
print(f"── 完成 {total} 張，共 {time.time()-t0:.0f}s ──")
