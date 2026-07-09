"""補跑轉換：讀 _auto_classify.json，每支上限 8 張，3 執行緒 + 429 退避重試，跳過已完成。"""
import base64, io, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from scratch_auto_pipeline import client, TOOLS, SYSTEM, INSTR, _uri

CAP = 8
spec = Path("config/design_engine/JOYSLU_LADY_DESIGN_ENGINE.md").read_text(encoding="utf-8")
cls = json.load(open("output/_auto_classify.json"))

def tx(item, stem):
    out = Path(f"output/{item}/images/shopee_1to1_final/{stem}_1to1.png")
    if out.exists(): return "快取"
    out.parent.mkdir(parents=True, exist_ok=True)
    content = [{"type":"input_text","text":spec+"\n\n"+INSTR},
               {"type":"input_image","image_url":_uri(Path(f"output/{item}/images/detail/{stem}.jpg"))}]
    for attempt in range(5):
        try:
            r = client.responses.create(model="gpt-5.5", instructions=SYSTEM,
                    input=[{"role":"user","content":content}], tools=TOOLS)
            imgs=[o for o in r.output if getattr(o,"type","")=="image_generation_call" and getattr(o,"result",None)]
            if imgs:
                out.write_bytes(base64.b64decode(imgs[0].result)); return "✓"
            return "沒生圖"
        except Exception as e:
            s=str(e)
            if "429" in s or "rate" in s.lower():
                time.sleep(15*(attempt+1)); continue
            return f"✗{s[:40]}"
    return "✗429重試耗盡"

jobs=[(i,s) for i,v in cls.items() for s in v["fullbody"][:CAP]]
todo=[(i,s) for i,s in jobs if not Path(f"output/{i}/images/shopee_1to1_final/{s}_1to1.png").exists()]
print(f"總 {len(jobs)} 張(上限{CAP}/支)，待補 {len(todo)} 張")
ok=0; done=0
with ThreadPoolExecutor(max_workers=3) as ex:
    futs=[ex.submit(tx,i,s) for i,s in todo]
    for f in as_completed(futs):
        done+=1; r=f.result()
        if r=="✓": ok+=1
        if done%20==0 or done==len(todo): print(f"  {done}/{len(todo)} 新成功累計 {ok}", flush=True)
print(f"完成，新增 {ok} 張")
