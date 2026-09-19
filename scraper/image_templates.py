"""圖片模板（提示檔）→ GPT 生圖（一份模板＝下拉選單一個選項，Edwin 2026-09-19 定）。

**加一種生法＝丟一份 md 進 `config/design_engine/{賣場}/`，程式不用改。**
檔案開頭可以用一小段設定宣告「生幾張、怎麼餵圖」（沒寫就用預設）：

```
---
張數: 9              # 預設 1（只生封面，第 2 張起沿用 1688 原圖）
輸入: 全部參考圖       # 或「對應原圖」：第 N 張拿 1688 第 N 張主圖去轉（Lady V2 那種「保留原圖只優化」）
板娘: 不用            # 用／不用（design_engine/persona/ 的品牌人物照）
對手參考: 不用         # 用／不用（design_engine/reference/ 的對手場景圖）
---
（以下整份是給生圖模型讀的規範）

### 第 1 張｜封面
### 第 2～5 張｜規格與賣點
```

每一張的指令＝整份規範 ＋「請產生第 N 張（共 M 張）」＋（有寫的話）那一張自己的段落。

- ⚠️ 板娘／對手參考**預設不用**：板娘是女裝的模特兒臉，Nail 的集塵器餵進去會生出奇怪的圖。
  要用的模板自己寫「板娘: 用」。
- ⚠️ 某一張生失敗 → 那一格退回 1688 原圖，並記在結果裡；不讓整支商品卡住。
- 生好的一組圖存在 `output/raw/{item_id}/images/generated/gpt/{模板}_{時間}/`，
  `set.json` 記每一格的檔案與圖床網址 → 之後「重生文案」照用這組、不重生也不再付錢。
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger

from config.settings import BASE_DIR

DESIGN_ROOT = Path(BASE_DIR) / "config" / "design_engine"
PERSONA_DIR = DESIGN_ROOT / "persona"
REFERENCE_DIR = DESIGN_ROOT / "reference"
PRICE_PER_IMAGE = 0.17          # gpt-image-1 1024x1024 high ≈ US$0.17／張
MAX_SLOTS = 9                   # 蝦皮商品圖上限 9 張

_KEYS = {"張數": "count", "輸入": "input", "板娘": "persona", "對手參考": "reference"}
_SLOT_RE = re.compile(r"^(#{2,4})\s*第\s*(\d+)\s*(?:[～~\-－至到]\s*(\d+))?\s*張")


@dataclass
class ImageTemplate:
    name: str
    path: Path
    count: int = 1
    input_mode: str = "全部參考圖"        # 或「對應原圖」
    use_persona: bool = False
    use_reference: bool = False
    spec: str = ""                        # 設定區以外的整份規範
    slot_notes: dict[int, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "封面 1 張" if self.count == 1 else f"{self.count} 張"

    def prompt_for(self, n: int) -> str:
        ask = ("請嚴格依上述規範，產生第一張「封面（Cover）」。" if self.count == 1
               else f"請嚴格依上述規範，產生第 {n} 張（共 {self.count} 張）。")
        note = self.slot_notes.get(n)
        return self.spec + "\n\n---\n" + ask + (f"\n\n這一張的要求：\n{note}" if note else "")


def list_templates(shop: str) -> list[Path]:
    """該賣場有哪幾份圖片模板（config/design_engine/{shop}/*.md）。"""
    d = DESIGN_ROOT / shop
    return sorted(d.glob("*.md")) if d.exists() else []


def _yes(v: str) -> bool:
    return str(v).strip() in ("用", "是", "要", "yes", "true", "1")


def parse_template(path: Path) -> ImageTemplate:
    text = Path(path).read_text(encoding="utf-8")
    t = ImageTemplate(name=Path(path).stem, path=Path(path))
    body = text
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or not re.search(r"[:：]", line):
                continue
            k, v = re.split(r"[:：]", line, 1)
            key = _KEYS.get(k.strip())
            v = v.strip()
            if key == "count":
                try:
                    t.count = max(1, min(MAX_SLOTS, int(re.sub(r"\D", "", v) or 1)))
                except ValueError:
                    logger.warning(f"圖片模板 {t.name}：張數「{v}」看不懂，當 1 張")
            elif key == "input":
                t.input_mode = "對應原圖" if "對應" in v else "全部參考圖"
            elif key == "persona":
                t.use_persona = _yes(v)
            elif key == "reference":
                t.use_reference = _yes(v)
    t.spec = body.strip()
    t.slot_notes = _slot_notes(t.spec, t.count)
    return t


def _slot_notes(spec: str, count: int) -> dict[int, str]:
    """「### 第 N 張」「### 第 2～5 張」段落 → {張次: 那一段文字}。"""
    lines = spec.splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = _SLOT_RE.match(ln.strip())
        if m:
            a = int(m.group(2))
            b = int(m.group(3) or a)
            heads.append((i, len(m.group(1)), a, b))
    out: dict[int, str] = {}
    for j, (i, lvl, a, b) in enumerate(heads):
        end = len(lines)
        for k in range(i + 1, len(lines)):
            h = re.match(r"^(#+)\s", lines[k])
            if h and len(h.group(1)) <= lvl:
                end = k
                break
        sec = re.sub(r"(\n\s*-{3,}\s*)+$", "", "\n".join(lines[i:end]).strip())   # 段尾的分隔線不算
        for n in range(a, min(b, count) + 1):
            out[n] = sec
    return out


def load_template(shop: str, name: str) -> ImageTemplate:
    p = DESIGN_ROOT / shop / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(
            f"找不到圖片模板：{p}\n沒有規範就沒有風格依據——不要拿別家的規範生圖")
    return parse_template(p)


# ── 一組生圖（一支商品 × 一份模板）────────────────────────────────
def _gpt_root(item_dir: Path) -> Path:
    return Path(item_dir) / "images" / "generated" / "gpt"


def latest_set(item_dir: Path) -> dict | None:
    """這支商品最近一次生的那組（沒有回 None）。"""
    p = _gpt_root(item_dir) / "latest.json"
    if not p.exists():
        return None
    try:
        ref = json.loads(p.read_text(encoding="utf-8"))
        return load_set(Path(ref["set"]))
    except Exception:  # noqa: BLE001
        return None


def load_set(set_dir: Path) -> dict | None:
    f = Path(set_dir) / "set.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _local_refs(product_data: dict, item_dir: Path) -> tuple[list[Path], list[Path]]:
    main_dir = Path(item_dir) / "images" / "main"
    detail_dir = Path(item_dir) / "images" / "detail"
    if not (main_dir.exists() and any(main_dir.glob("*.*"))):
        from scraper.downloader import download_product_images_from_json
        logger.info("下載 1688 圖當 GPT 參考…")
        asyncio.run(download_product_images_from_json(product_data, Path(item_dir) / "images"))
    mains = sorted(main_dir.glob("*.*")) if main_dir.exists() else []
    details = sorted(detail_dir.glob("*.*")) if detail_dir.exists() else []
    return mains, details


def generate_set(product_data: dict, item_dir: Path, code: str, shop: str,
                 template: str, log=logger.info) -> dict:
    """照模板生一組圖 → 上圖床 → 存 set.json 並設成這支的最新一組。

    回 {"template", "dir", "count", "slots": [{"n", "file", "url"}], "failed": [n…]}。
    失敗的格子 file/url 為 None（組 Excel 時退回 1688 原圖）。
    """
    from ecommerce_media.image_gen import generate_image, list_images
    from scraper.image_host import is_configured, upload_image

    t = load_template(shop, template)
    if not is_configured():
        raise RuntimeError("圖床未設定（SUPABASE_URL／SUPABASE_SERVICE_KEY），GPT 圖傳不上去")
    mains, details = _local_refs(product_data, item_dir)
    persona = list_images(PERSONA_DIR, 3) if t.use_persona else []
    refs = list_images(REFERENCE_DIR, 3) if t.use_reference else []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    set_dir = _gpt_root(item_dir) / f"{re.sub(r'[^\w-]', '_', t.name)}_{stamp}"
    set_dir.mkdir(parents=True, exist_ok=True)

    slots, failed = [], []
    for n in range(1, t.count + 1):
        if t.input_mode == "對應原圖":
            base = [mains[n - 1]] if n - 1 < len(mains) else []
        else:
            base = mains[:6] + details[:3]
        if not base:
            log(f"[{code}] 第 {n} 張：沒有可用的 1688 原圖當參考 → 這格沿用 1688")
            slots.append({"n": n, "file": None, "url": None})
            failed.append(n)
            continue
        log(f"[{code}] ✨ GPT 生第 {n}/{t.count} 張（模板 {t.name}）…")
        out = generate_image(base + persona + refs, t.prompt_for(n), set_dir / f"slot_{n:02d}.png")
        url = upload_image(out, f"{code}/gpt/{stamp}/{out.name}") if out else None   # 圖床路徑只放英數（模板名可能是中文）
        if not url:
            failed.append(n)
            log(f"[{code}] ⚠️ 第 {n} 張{'沒生出來' if not out else '上傳圖床失敗'} → 這格沿用 1688 原圖")
        slots.append({"n": n, "file": str(out) if out else None, "url": url})

    doc = {"template": t.name, "dir": str(set_dir), "count": t.count,
           "created": stamp, "slots": slots, "failed": failed}
    (set_dir / "set.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (_gpt_root(item_dir) / "latest.json").write_text(
        json.dumps({"set": str(set_dir)}, ensure_ascii=False), encoding="utf-8")
    return doc


def merge_images(gpt_set: dict | None, base_urls: list[str]) -> list[str]:
    """GPT 那組 × 1688 原圖 → 上架檔商品圖（最多 9 張）。

    第 N 格：GPT 有生出來就用 GPT，沒有就用 1688 同位置那張。
    模板只生封面時＝[GPT 封面, 1688 第 2~9 張]（舊版會把 1688 其餘 8 張整組丟掉，只剩 1 張圖）。
    """
    out = list(base_urls[:MAX_SLOTS])
    if not gpt_set:
        return out
    for s in gpt_set.get("slots", []):
        i = int(s["n"]) - 1
        if not s.get("url") or i >= MAX_SLOTS:
            continue
        if i < len(out):
            out[i] = s["url"]
        else:
            out.append(s["url"])
    return out


def set_files(gpt_set: dict | None) -> list[Path]:
    """這組實際生出來的本機圖（給影片、素材夾用）。"""
    if not gpt_set:
        return []
    return [Path(s["file"]) for s in gpt_set.get("slots", []) if s.get("file") and Path(s["file"]).exists()]
