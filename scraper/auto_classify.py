"""視覺自動分類 1688 細節圖（取代人工挑圖 + 人工讀尺碼表）。
- classify_details(item)：contact sheet → 一次 vision 呼叫 → {fullbody:[stem], sizechart: stem}
- read_size_chart(img)：全解析尺碼圖 → vision → {product_type, headers, rows, weight_jin_by_size}
用 gpt-5.5 vision（Responses API）。"""
import base64
import io
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)
from openai import OpenAI
from PIL import Image, ImageDraw

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _b64(im: Image.Image, fmt="JPEG", q=85) -> str:
    b = io.BytesIO()
    im.convert("RGB").save(b, fmt, quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def _uri_file(p: Path, cap=1024) -> str:
    im = Image.open(p)
    m = max(im.size)
    if m > cap:
        s = cap / m
        im = im.resize((int(im.width * s), int(im.height * s)))
    return _b64(im)


def _contact_sheet(files: list[Path]) -> str:
    cols = 6
    tw, th, pad = 200, 270, 26
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + pad) + 20), "white")
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        im.thumbnail((tw - 8, th - 8))
        x = (i % cols) * tw
        y = 20 + (i // cols) * (th + pad)
        sheet.paste(im, (x + 4, y + 16))
        d.text((x + 4, y + 2), f.stem.replace("detail_", "#"), fill="black")
    return _b64(sheet)


def _json_from(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m.group(0)) if m else {}


def classify_details(item: str, subdir: str = "detail") -> dict:
    """回 {fullbody: [stem…], sizechart: stem|None}。subdir 可用 'main'（無細節圖時退主圖）。"""
    files = sorted(Path(f"output/{item}/images/{subdir}").glob("*.*"))
    if not files:
        return {"fullbody": [], "sizechart": None}
    prompt = (
        "這是一個 1688 女裝商品的細節圖縮圖總表，每張左上標了編號 #NNN。請分類並回 JSON：\n"
        "1. fullbody：乾淨的『全身模特試穿圖』編號清單——看得到完整或近全身的人穿著該褲/裙、"
        "可直接當蝦皮商品圖、且『沒有大面積簡體行銷疊字』的那些（有小 logo/角落字可接受）。"
        "只挑最能賣的全身圖，半身特寫/布料特寫/純文字面板都不要。\n"
        "2. sizechart：尺碼表那張的編號（含 S/M/L 與腰圍/臀圍/褲長等數字表格）；沒有就 null。\n"
        '回格式：{"fullbody": ["#012","#016",…], "sizechart": "#007"}（用縮圖上的 #編號）'
    )
    content = [{"type": "input_text", "text": prompt},
               {"type": "input_image", "image_url": _contact_sheet(files)}]
    resp = client.responses.create(model="gpt-5.5",
                                   input=[{"role": "user", "content": content}])
    data = _json_from(getattr(resp, "output_text", "") or "")
    stems = {f.stem for f in files}

    def norm(x):
        s = str(x).strip().replace("#", "")
        return f"detail_{int(s):03d}" if s.isdigit() else s
    fb = [norm(x) for x in data.get("fullbody", [])]
    fb = [s for s in fb if s in stems]
    sc = norm(data.get("sizechart")) if data.get("sizechart") else None
    sc = sc if sc in stems else None
    return {"fullbody": fb, "sizechart": sc}


def extract_highlights(image_paths: list, max_images: int = 10) -> dict:
    """讀商品詳情圖 → 條列廠商印在圖上的「賣點/規格重點」（文字屬性表抓不到的）。

    通用（女裝/美甲/3C 皆可）：燈珠數、功率、波長、容量、機能優勢、材質工藝、適用場景等。
    逐張送（不用縮圖總表，才讀得清圖上小字）；回
    {"highlights": ["72 顆雙排燈珠", "紅光不使手部顯黑", …], "specs": {"功率": "48W", …}}。
    """
    files = [Path(p) for p in image_paths if Path(p).exists()][:max_images]
    if not files:
        return {"highlights": [], "specs": {}}
    prompt = (
        "這是一個 1688 商品的詳情圖（同一件商品的多張）。請讀出廠商在圖片上主打的"
        "「商品賣點與規格重點」——就是印在圖上、一般文字屬性表沒有的特色，例如：\n"
        "· 規格數字（燈珠數/功率/波長/容量/尺寸/入數等）→ 放 specs\n"
        "· 機能與優勢（如『紅光不使手部顯黑』『免洗封層』『速乾』『一秒定位』）→ 放 highlights\n"
        "· 材質工藝、適用場景/對象、對比競品的優點 → 放 highlights\n\n"
        "【務必過濾，不要收進來】：\n"
        "· 出貨/物流備註（如『新舊款隨機發貨』『迭代過渡期』『拍前聯繫客服』『介意勿拍』）\n"
        "· 空泛行銷虛詞（單獨的『全新升級』『更大空間』『高品質』『廠家直銷』這種沒有具體內容的）\n"
        "· 純情緒字（『超值』『爆款』『熱賣』）\n"
        "· 平台/店鋪/售後/發票相關\n\n"
        "【要求】：每條賣點是**具體、獨立、可查證**的一句話；語意重複的合併成一條（如『大空間』"
        "＋『可容納雙手』→ 合成一條『燈口寬敞可容納雙手照燈』）；具體數字盡量進 specs 不要重複進 highlights。"
        "忠實照抄圖上文字、不腦補。回 JSON：\n"
        '{"highlights": ["具體賣點1", "具體賣點2", …], "specs": {"規格項": "值"}}\n'
        "highlights 控制在約 6-10 條精華；specs 放明確規格數字（找不到給空物件 {}）。"
    )
    content = [{"type": "input_text", "text": prompt}] + \
              [{"type": "input_image", "image_url": _uri_file(p, cap=1100)} for p in files]
    resp = client.responses.create(model="gpt-5.5",
                                   input=[{"role": "user", "content": content}])
    data = _json_from(getattr(resp, "output_text", "") or "")
    data.setdefault("highlights", [])
    data.setdefault("specs", {})
    return data


def read_size_chart(item: str, stem: str) -> dict:
    """讀尺碼表 → {product_type:'褲'|'裙', headers:[...], rows:[[...]], weight_jin:{size:'80-95'}}。"""
    p = Path(f"output/{item}/images/detail/{stem}.jpg")
    if not p.exists():
        return {}
    prompt = (
        "讀出這張 1688 尺碼表的所有數據，忠實照抄數字，回 JSON：\n"
        '{"product_type":"褲 或 裙",'
        '"headers":["尺碼","小個子褲長","常規款褲長","加長款褲長","腰圍","臀圍"](照實際欄位，褲=褲長/裙=裙長，有幾種長度就幾欄),'
        '"rows":[["S","93","98","103","61","102"],…](每列含尺碼+各數字),'
        '"weight_jin":{"S":"80-95","M":"96-110",…}}\n'
        "⚠️ weight_jin 很重要：圖上通常有「適合80-180斤」大字 + 每個尺碼標「建議體重 XX-YY斤」"
        "（可能在色塊/圓圈/表格最右欄裡），請務必逐一找出每個尺碼的斤數範圍填入；真的完全沒有才給空物件。"
    )
    content = [{"type": "input_text", "text": prompt},
               {"type": "input_image", "image_url": _uri_file(p, cap=1400)}]
    resp = client.responses.create(model="gpt-5.5",
                                   input=[{"role": "user", "content": content}])
    return _json_from(getattr(resp, "output_text", "") or "")


if __name__ == "__main__":
    import sys
    it = sys.argv[1] if len(sys.argv) > 1 else "953732723854"
    c = classify_details(it)
    print("classify:", c)
    if c["sizechart"]:
        print("size_chart:", json.dumps(read_size_chart(it, c["sizechart"]), ensure_ascii=False))
