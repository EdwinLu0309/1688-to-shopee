"""
蝦皮商品短影片合成（把本機圖片合成 1:1 mp4）。

合成核心（build_ffmpeg_args / 常數）移植自
`listing-optimization-tool/tools/shopee-video-batch/batch.py`，
差別在於來源改成「本機已下載的 1688 圖片」而非從蝦皮賣場 API 抓。
跨 repo import 太脆弱，故複製一份在此維護。

用法：
    from scraper.video_maker import make_product_video
    make_product_video(Path("output/683456636600"))  # 隨機挑 9 張 → video/683456636600.mp4
"""
import random
import subprocess
from pathlib import Path

# ffmpeg-static（先在 tools/video-maker 跑過 npm install）
_FFMPEG = (
    Path.home()
    / "projects/listing-optimization-tool/tools/video-maker/node_modules/ffmpeg-static/ffmpeg"
)
_MUSIC_DIR = Path.home() / "projects/listing-optimization-tool/tools/shopee-video-batch/music"

# 影片參數（對齊蝦皮商品頁影片：1:1、每張 2.5s、淡入淡出、≥11s）
W, H, DUR, TRANS, TRANS_DUR, FPS = 1080, 1080, 2.5, True, 0.5, 30
MIN_DURATION = 11.0


def build_ffmpeg_args(image_paths: list[Path], out_path: Path, music_path: Path | None) -> list[str]:
    n = len(image_paths)
    dur = DUR
    total = dur if n == 1 else (n * dur - (n - 1) * TRANS_DUR if TRANS else n * dur)
    if total < MIN_DURATION:  # 圖少 → 拉長每張秒數補到下限
        if n == 1:
            dur = MIN_DURATION
        elif TRANS:
            dur = (MIN_DURATION + (n - 1) * TRANS_DUR) / n
        else:
            dur = MIN_DURATION / n
        total = dur if n == 1 else (n * dur - (n - 1) * TRANS_DUR if TRANS else n * dur)

    args: list[str] = []
    for p in image_paths:
        args += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(p)]
    music_idx = -1
    if music_path and Path(music_path).exists():
        music_idx = n
        args += ["-i", str(music_path)]

    filters = []
    for i in range(n):
        filters.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1,fps={FPS},format=yuv420p[v{i}]"
        )
    if n == 1:
        last = "v0"
    elif not TRANS:
        ins = "".join(f"[v{i}]" for i in range(n))
        filters.append(f"{ins}concat=n={n}:v=1:a=0[vout]")
        last = "vout"
    else:
        prev = "v0"
        for k in range(1, n):
            out = "vout" if k == n - 1 else f"x{k}"
            off = f"{k * (dur - TRANS_DUR):.3f}"
            filters.append(
                f"[{prev}][v{k}]xfade=transition=fade:duration={TRANS_DUR}:offset={off}[{out}]"
            )
            prev = out
        last = "vout"
    if music_idx >= 0:
        fade = max(0, total - 1.2)
        filters.append(f"[{music_idx}:a]volume=0.85,afade=t=out:st={fade:.2f}:d=1.2[aout]")

    args += ["-filter_complex", ";".join(filters), "-map", f"[{last}]"]
    if music_idx >= 0:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    args += [
        "-t", f"{total:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-movflags", "+faststart", "-y", str(out_path),
    ]
    return args


def _pick_music(item_id: str) -> Path | None:
    """從 music/ 挑一首（依 item_id 輪播，整批不同商品換不同曲）。"""
    if not _MUSIC_DIR.exists():
        return None
    tracks = sorted(p for p in _MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".aac", ".wav"))
    if not tracks:
        return None
    idx = sum(ord(c) for c in item_id) % len(tracks)  # 穩定但分散
    return tracks[idx]


_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def collect_images(item_dir: Path, prefer_clean: bool = True) -> list[Path]:
    """收集商品資料夾內可用的圖片。

    prefer_clean=True（預設）：**主圖 + SKU 圖優先，detail 排最後**。
    因為 1688 的 detail（細節圖 = 描述 HTML 內的圖）幾乎都是簡體行銷文案圖/尺碼表，
    不適合直接上架；主圖（主商品圖）通常是乾淨的模特兒穿搭/商品圖。做影片時前面
    的圖會被優先挑到，自然避開簡體 detail 圖。
    """
    images_dir = item_dir / "images"

    def glob_sub(sub: str) -> list[Path]:
        d = images_dir / sub
        return sorted(p for p in d.glob("*.*") if p.suffix.lower() in _IMG_EXT) if d.exists() else []

    order = ("main", "sku", "detail") if prefer_clean else ("main", "detail", "sku")
    pool: list[Path] = []
    for sub in order:
        pool += glob_sub(sub)
    return pool


def make_product_video(
    item_dir: Path,
    n: int = 9,
    name: str | None = None,
    music_path: Path | None = None,
    seed: int | None = None,
    images: list[Path] | None = None,
) -> Path | None:
    """合成 1:1 短影片 → item_dir/video/{name}.mp4。

    images：明確指定要用的圖片清單（按此順序），適合人工挑好乾淨穿搭圖後傳入。
            不傳則從 item_dir 收圖（主圖/SKU 優先、detail 最後），取前 n 張。
    Returns 影片路徑；ffmpeg 不存在或無圖回 None。
    """
    if not _FFMPEG.exists():
        raise FileNotFoundError(
            f"找不到 ffmpeg：{_FFMPEG}\n   先到 tools/video-maker 跑 `npm install`"
        )

    if images:
        # 明確指定：只用存在的檔，按給定順序
        images = [Path(p) for p in images if Path(p).exists()]
        if not images:
            return None
    else:
        pool = collect_images(item_dir)
        if not pool:
            return None
        # 主圖/SKU 已排前面：取前 n 張（自然避開後面的簡體 detail 圖），不再隨機
        images = pool[:n]

    item_id = name or item_dir.name
    video_dir = item_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    out = video_dir / f"{item_id}.mp4"

    music = music_path or _pick_music(item_id)
    args = [str(_FFMPEG)] + build_ffmpeg_args(images, out, music)
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失敗：{r.stderr[-400:]}")
    return out
