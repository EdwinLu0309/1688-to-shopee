"""全自動圖片 pipeline（走 A）：對一批已抓取的商品，自動
1. 視覺分類細節圖（挑全身圖 + 找尺碼表）
2. 逐張轉換全身圖 → 蝦皮 1:1 繁體（gpt-image-1.5 low + V2）— ThreadPool 併發
3. 讀尺碼表數據 → 生繁體尺碼表（體重可選，斤→kg）
可重跑（已完成的跳過）。用法：python scratch_auto_pipeline.py [item_id...]（省略=讀 _p14ae6plus.json）
"""
import base64
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)
from openai import OpenAI
from PIL import Image

from scraper.auto_classify import classify_details, read_size_chart
from scraper.size_chart_maker import make_size_chart

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
MODEL_IMG, QUALITY = "gpt-image-1.5", "low"
TOOLS = [{"type": "image_generation", "model": MODEL_IMG, "size": "1024x1024", "quality": QUALITY}]

SYSTEM = ("Reframe the uploaded product photo into a 1:1 square for Taiwan Shopee. Do NOT treat "
          "'preserve the whole image' as the top priority. Priority: (1) product authenticity — "
          "never alter garment, fabric, color, wrinkles, sheen, pose, model, face, body; (2) make "
          "the PRODUCT AS LARGE AS POSSIBLE; (3) full body visible; (4) centered; (5) 1:1; (6) keep "
          "background. To fill the square, FIRST enlarge the subject, THEN extend the existing "
          "background (same wall/floor/color temp/lighting) via smart-crop. NEVER shrink the whole "
          "image or add white/polaroid borders. Person ~82-88% of height, feet 2-4% from bottom, "
          "head 3-5% from top. Simplified Chinese → Traditional; remove English-only decorative "
          "text. Never crop the product. LOCK COLORS: grey stays neutral grey, never shift blue. "
          "Output must look like a real reframed photo, not AI-generated.")
INSTR = ("請把這張 1688 模特圖轉成 1:1 蝦皮商品圖：智慧裁背景+延伸原背景讓人物填滿約 82-88% 畫面、"
         "水平置中，絕不整張縮小或加白邊。簡體改繁體、刪純英文字。商品/模特/布料/顏色/姿勢 100% 保留不重畫。"
         "⚠️嚴格鎖色：灰色維持中性灰不可偏藍。")


def _uri(p, cap=1024):
    im = Image.open(p).convert("RGB")
    m = max(im.size)
    if m > cap:
        s = cap / m
        im = im.resize((int(im.width * s), int(im.height * s)))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def transform_one(item, stem, spec):
    out = Path(f"output/{item}/images/shopee_1to1_final/{stem}_1to1.png")
    if out.exists():
        return f"{item}/{stem} (快取)"
    out.parent.mkdir(parents=True, exist_ok=True)
    src = Path(f"output/{item}/images/detail/{stem}.jpg")
    content = [{"type": "input_text", "text": spec + "\n\n" + INSTR},
               {"type": "input_image", "image_url": _uri(src)}]
    for attempt in range(5):
        try:
            r = client.responses.create(model="gpt-5.5", instructions=SYSTEM,
                                        input=[{"role": "user", "content": content}], tools=TOOLS)
            imgs = [o for o in r.output if getattr(o, "type", "") == "image_generation_call" and getattr(o, "result", None)]
            if imgs:
                out.write_bytes(base64.b64decode(imgs[0].result))
                return f"{item}/{stem} ✓"
            return f"{item}/{stem} ✗ 沒生圖"
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "rate" in str(e).lower():
                time.sleep(15 * (attempt + 1))
                continue
            return f"{item}/{stem} ✗ {str(e)[:50]}"
    return f"{item}/{stem} ✗ 429重試耗盡"


def _jin_to_kg(rng):
    try:
        a, b = re.split(r"[-~－]", str(rng))
        return f"{float(a)/2:g}-{float(b)/2:g}"
    except Exception:
        return None


import re  # noqa: E402


def gen_size_chart(item, code, sc_stem):
    if not sc_stem:
        return "無尺碼表"
    data = read_size_chart(item, sc_stem)
    headers = data.get("headers") or []
    rows = data.get("rows") or []
    if not headers or not rows:
        return "尺碼表讀取失敗"
    wj = data.get("weight_jin") or {}
    kg = {s: _jin_to_kg(v) for s, v in wj.items()}
    kg = {s: v for s, v in kg.items() if v}
    if kg:
        note = "建議體重：" + "｜".join(f"{s} {v}" for s, v in kg.items()) + "（kg）。因人工測量，尺寸容許 1-3cm 誤差。"
    else:
        note = "因人工測量，尺寸容許 1-3cm 誤差。"
    out = Path(f"output/{item}/images/generated/size_chart_{code}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    make_size_chart([str(h) for h in headers], [[str(c) for c in r] for r in rows], out, title="尺碼表", note=note)
    return f"尺碼表 ✓ ({len(rows)}列, 體重{'有' if kg else '無'})"


def main():
    from scraper.ai_list_reader import parse_ai_list_csv
    csv = os.environ.get("AILIST", "input/lady_ai_list_014.csv")
    idsfile = os.environ.get("IDSFILE", "input/_p14ae6plus.json")
    rows = parse_ai_list_csv(csv)
    code_of = {r["item_id"]: r["code"] for r in rows}
    ids = sys.argv[1:] or json.load(open(idsfile))
    ids = [i for i in ids if Path(f"output/{i}/images/detail").exists() and
           list(Path(f"output/{i}/images/detail").glob("*.*"))]
    print(f"處理 {len(ids)} 個有圖的商品")

    # 1) 分類（併發）
    t0 = time.time()
    cls = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(classify_details, i): i for i in ids}
        for f in as_completed(futs):
            i = futs[f]
            try:
                cls[i] = f.result()
            except Exception as e:  # noqa: BLE001
                cls[i] = {"fullbody": [], "sizechart": None}
                print(f"  {i} 分類失敗 {str(e)[:50]}")
            print(f"  分類 {code_of.get(i,i)}: 全身{len(cls[i]['fullbody'])}張 尺碼表={cls[i]['sizechart']}")
    print(f"── 分類完成 {time.time()-t0:.0f}s ──")

    # 2) 轉換全身圖（併發）
    jobs = [(i, s) for i in ids for s in cls[i]["fullbody"]]
    print(f"轉換 {len(jobs)} 張全身圖（3緒+退避）…")
    spec = Path("config/design_engine/JOYSLU_LADY_DESIGN_ENGINE.md").read_text(encoding="utf-8")
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(transform_one, i, s, spec) for i, s in jobs]
        for f in as_completed(futs):
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} {f.result()}")
    print(f"── 轉換完成 {time.time()-t0:.0f}s ──")

    # 3) 尺碼表（併發）
    print("生尺碼表…")
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(gen_size_chart, i, code_of.get(i, i), cls[i]["sizechart"]): i for i in ids}
        for f in as_completed(futs):
            i = futs[f]
            print(f"  {code_of.get(i,i)}: {f.result()}")

    # 存分類結果供後續打包用
    json.dump({i: cls[i] for i in ids}, open("output/_auto_classify.json", "w"), ensure_ascii=False, indent=1)
    print("分類結果存 output/_auto_classify.json")


if __name__ == "__main__":
    main()
