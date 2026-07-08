"""純測試：只丟 md + 圖片 → gpt-image-1 → 9 張。不加任何導演/指令/自主觀念。"""
from pathlib import Path
from scraper.gpt_image_generator import _edit, load_design_spec, _imgs, PERSONA_DIR, REFERENCE_DIR

item = "953732723854"
spec = load_design_spec()  # ← prompt 就是 md 原文，什麼都不加

mains = sorted(Path(f"output/{item}/images/main").glob("*.*"))[:6]        # 商品圖
skus = [Path(f"output/{item}/images/sku/sku_00{i}.jpg") for i in range(4)]  # 選項圖(色卡)
persona = _imgs(PERSONA_DIR, 2)      # 老闆娘
ref = _imgs(REFERENCE_DIR, 3)        # 3 張參考
imgs = mains + skus + persona + ref
print(f"餵 {len(imgs)} 張（商品{len(mains)} + 色卡{len(skus)} + 老闆娘{len(persona)} + 參考{len(ref)}）")

outdir = Path(f"output/{item}/images/pure_set")
ok = 0
for i in range(1, 10):
    out = _edit(imgs, spec, outdir / f"pure_{i:02d}.png")
    print(f"{i}/9 -> {out}")
    if out:
        ok += 1
print(f"完成 {ok}/9 張，位於 {outdir}")
