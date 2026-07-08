"""Sprint B：Responses API（GPT-5.5 → image_generation）跑 9 張。零加工，只送 md + 圖。"""
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
spec = load_design_spec()  # md 原文，不加工

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
print(f"送 {len(paths)} 張 + md {len(spec)} 字，跑 9 張…")

outdir = Path(f"output/{item}/images/responses_set")
outdir.mkdir(parents=True, exist_ok=True)
ok = 0
for i in range(1, 10):
    try:
        resp = client.responses.create(
            model="gpt-5.5",
            input=[{"role": "user", "content": content}],
            tools=[{"type": "image_generation", "size": "1024x1024", "quality": "high"}],
        )
        outs = [o for o in resp.output
                if getattr(o, "type", "") == "image_generation_call" and getattr(o, "result", None)]
        if outs:
            dst = outdir / f"B_{i:02d}.png"
            dst.write_bytes(base64.b64decode(outs[0].result))
            ok += 1
            print(f"{i}/9 -> {dst}")
        else:
            print(f"{i}/9 沒生圖，只回文字：{(getattr(resp,'output_text','') or '')[:120]}")
    except Exception as e:  # noqa: BLE001
        print(f"{i}/9 ✗ {str(e)[:150]}")
print(f"完成 {ok}/9，位於 {outdir}")
