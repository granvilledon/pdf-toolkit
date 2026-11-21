# -*- coding: utf-8 -*-
"""阶段1：大字标题行/色块行检测（只读）。
渲染 dpi60 全页 -> 水平投影分行 -> 行高>=1.55*中位 且 y<42% 记为候选；
彩页另测色块条（饱和度+宽度）。输出每本书的候选页统计。
用于：扫描件加目录前定位「整页大字分隔页」。

用法：python detect_bigtitle_pages.py [--root DIR] [--files a.pdf,b.pdf]
    不传 --files 时递归扫描 --root 下全部 PDF。
"""
import os, sys, json, argparse
import numpy as np
import fitz

from common import load_config, resolve

ap = argparse.ArgumentParser(description="扫描件大字分隔页检测（只读）")
ap.add_argument("--config")
ap.add_argument("--root")
ap.add_argument("--files", help="逗号分隔的文件相对路径；缺省=递归扫 root 全部 PDF")
args = ap.parse_args()

CFG = load_config(args.config)
if args.root:
    CFG["root"] = args.root

if args.files:
    TARGETS = [s.strip() for s in args.files.split(",") if s.strip()]
else:
    TARGETS = []
    for dp, dn, fn in os.walk(CFG["root"]):
        if "_backup" in dp:
            continue
        for f in sorted(fn):
            if f.lower().endswith(".pdf"):
                TARGETS.append(os.path.relpath(os.path.join(dp, f), CFG["root"]))
print(f"待检测 {len(TARGETS)} 本", flush=True)


def rows_of(gray, thr=185):
    ink = gray < thr
    prof = ink.mean(axis=1)
    rows = []
    in_row = False
    for y, v in enumerate(prof):
        if not in_row and v > 0.012:
            y0 = y; in_row = True
        elif in_row and v <= 0.012:
            rows.append((y0, y)); in_row = False
    if in_row:
        rows.append((y0, len(prof)))
    return rows, ink


def analyze_page(pix):
    """返回 (大字行列表[(yfrac,hfrac,wfrac)], 色块行bool)"""
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    rgb = a[:, :, :3].astype(np.int16)
    gray = rgb.mean(axis=2)
    rows, ink = rows_of(gray)
    if not rows:
        return [], False
    hs = [b - y for y, b in rows]
    med = np.median(hs)
    big = []
    for (y0, y1), h in zip(rows, hs):
        if h >= med * 1.55 and h >= 6:
            seg = ink[y0:y1]
            w = seg.any(axis=0)
            xs = np.where(w)[0]
            if len(xs) == 0:
                continue
            ww = (xs[-1] - xs[0]) / gray.shape[1]
            if ww > 0.10:
                big.append((y0 / gray.shape[0], h / gray.shape[0], ww))
    # 色块行：饱和度高的整行横条
    sat = (rgb.max(axis=2) - rgb.min(axis=2)) > 40
    color_bar = None
    for (y0, y1), h in zip(rows, hs):
        if h >= 8 and h >= med * 1.3:
            band = sat[y0:y1]
            if band.mean() > 0.25 and band.any(axis=1).mean() > 0.5:
                color_bar = (y0 / gray.shape[0], h / gray.shape[0])
                break
    return big, color_bar


def main():
    out = {}
    for rel in TARGETS:
        fp = resolve(CFG, rel) if not os.path.isabs(rel) else rel
        d = fitz.open(fp)
        cands = {}
        for i in range(d.page_count):
            pix = d.load_page(i).get_pixmap(dpi=60)
            big, cbar = analyze_page(pix)
            if big or cbar:
                cands[i + 1] = {'big': [(round(a, 3), round(b, 3), round(c, 2)) for a, b, c in big],
                                'cbar': [round(cbar[0], 3), round(cbar[1], 3)] if cbar else None}
        d.close()
        out[rel] = cands
        nbar = sum(1 for v in cands.values() if v['cbar'])
        print(f"{rel.split('/')[-1][:40]:42s} 候选页 {len(cands):4d}  其中色块页 {nbar}", flush=True)
    json.dump(out, open(os.path.join(HERE, 'bigline_cand.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    print('DONE')


if __name__ == '__main__':
    main()
