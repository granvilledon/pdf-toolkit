# -*- coding: utf-8 -*-
"""扫描件水印固定区域覆盖 + 原件备份（可回滚）

用法：
    python remove_wm_scan_cover.py <file.pdf:left> [file2.pdf:right ...] [--config c.json] [--root DIR]
    file:left  = 覆盖左下角；file:right = 覆盖右下角。--write 才写盘，默认 dry-run。
    安全机制：区域内非白密度 > DENSITY_CAP（0.40）视为正文页，自动跳过防误伤；
              写盘前原件 MD5 备份到 backup_dir 并生成可回滚映射表 CSV。
"""
import os, sys, csv, hashlib, shutil, datetime, argparse
import fitz
import numpy as np

from common import load_config, resolve, md5_of

WRITE = "--write" in sys.argv
ap = argparse.ArgumentParser(description="扫描件页脚水印固定区域覆盖（dry-run 默认）")
ap.add_argument("targets", nargs="+", help="文件:side（left/right），路径相对 --root")
ap.add_argument("--config")
ap.add_argument("--root")
ap.add_argument("--write", action="store_true", help="写盘（默认 dry-run）")
args = ap.parse_args()
WRITE = args.write

CFG = load_config(args.config)
if args.root:
    CFG["root"] = args.root
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_cover")
os.makedirs(TMP, exist_ok=True)
if WRITE:
    os.makedirs(CFG["backup_dir"], exist_ok=True)

DENSITY_CAP = 0.40   # 区域内非白密度超过此值视为正文，跳过

def region_rect(page, side):
    r = page.rect
    if side == "right":
        return fitz.Rect(r.x0 + r.width * 0.55, r.y1 - r.height * 0.10, r.x1, r.y1)
    else:
        return fitz.Rect(r.x0, r.y1 - r.height * 0.105, r.x0 + r.width * 0.42, r.y1)

def density(page, clip):
    pix = page.get_pixmap(dpi=60, colorspace=fitz.csGRAY, clip=clip)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return float((a < 225).mean())

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

rows = []
for spec in args.targets:
    fn, _, side = spec.rpartition(":")
    if side not in ("left", "right"):
        raise SystemExit(f"参数格式应为 文件.pdf:left|right，收到：{spec}")
    fp = resolve(CFG, fn) if not os.path.isabs(fn) else fn
    if not os.path.exists(fp):
        print("缺失", fn, flush=True)
        continue
    doc = fitz.open(fp)
    n = doc.page_count
    covered = skipped = 0
    if WRITE:
        for i in range(n):
            pg = doc.load_page(i)
            rr = region_rect(pg, side)
            d = density(pg, rr)
            if d > DENSITY_CAP:
                skipped += 1
                continue
            pg.draw_rect(rr, color=None, fill=(1, 1, 1))
            covered += 1
        out = os.path.join(TMP, fn)
        doc.save(out, garbage=3, deflate=True)
    else:
        for i in range(n):
            pg = doc.load_page(i)
            rr = region_rect(pg, side)
            if density(pg, rr) > DENSITY_CAP:
                skipped += 1
            else:
                covered += 1
    doc.close()
    print(f'{"WILL" if WRITE else "DRY "} {fn[:50]}: {n}p 覆盖={covered} 跳过={skipped}', flush=True)
    if WRITE:
        if covered == 0:
            print("     无需处理，跳过替换", flush=True)
            continue
        bak_path = os.path.join(CFG["backup_dir"], fn.replace("/", "_"))
        if os.path.exists(bak_path):
            raise SystemExit(f"!! 备份目录已存在同名文件，中止以防覆盖：{fn}")
        src_md5 = md5(fp)
        bak = bak_path
        shutil.move(fp, bak)
        shutil.move(out, fp)
        assert md5(bak) == src_md5, "备份哈希不一致 " + fn
        rows.append({"文件名": fn, "MD5": src_md5,
                     "页数": n, "覆盖页": covered, "跳过页": skipped,
                     "时间": datetime.datetime.now().strftime("%m-%d %H:%M")})
        print(f'     备份OK {src_md5[:8]}', flush=True)

if WRITE and rows:
    csvp = os.path.join(CFG["backup_dir"], "000-覆盖映射表-可回滚.csv")
    with open(csvp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("映射表", csvp)
print("DONE write=", WRITE, flush=True)
