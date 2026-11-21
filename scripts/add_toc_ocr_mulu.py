# -*- coding: utf-8 -*-
"""印刷目录解析器：OCR 目录页 -> 条目(标题,印刷页码) -> 页脚校准 delta -> 书签
前置：先用 detect_bigtitle_pages.py / 人工翻页得到每本书的目录页清单（--pages JSON，
      结构 {"相对路径": {"toc_pages": [物理页号, ...]}}）。
用法：python add_toc_ocr_mulu.py <dry|write> [--pages xxx.json] [--config c.json] [--only 关键词]
依赖：RapidOCR（rapidocr-onnxruntime），见 ocr_lib.py
"""
import os, re, sys, json, time, argparse
import fitz, numpy as np
from PIL import Image
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "."))
from ocr_lib import ocr_lines  # noqa: E402

from common import load_config, resolve  # noqa: E402

ap = argparse.ArgumentParser(description="印刷目录 OCR 解析 -> 写书签（dry 默认）")
ap.add_argument("mode", nargs="?", default="dry", choices=["dry", "write"])
ap.add_argument("--pages", default="scan_tocpages.json", help="目录页清单 JSON（相对脚本目录或绝对路径）")
ap.add_argument("--config")
ap.add_argument("--root")
ap.add_argument("--only", default=None, help="只处理路径含此关键词的书")
args = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = load_config(args.config)
if args.root:
    CFG["root"] = args.root
ROOT = CFG["root"]
SCAN = json.load(open(args.pages if os.path.isabs(args.pages) else os.path.join(HERE, args.pages), encoding="utf-8"))
WRITE = args.mode == "write"
ONLY = args.only

RE_ENTRY = re.compile(r"^(.{2,48}?)[\s.·…·]*(\d{1,3})$")
RANK = [(re.compile(r"^(第[一二三四五六七八九十]+(部分|篇|编|科目)|Part\s*[IVX1-9]|专题\d)"), 1),
        (re.compile(r"^(第[一二三四五六七八九十百]+章|Passage\s*\d+|Text\s*\d+| Unit\s*\d)", re.I), 1),
        (re.compile(r"^(第[一二三四五六七八九十百]+节|\d+\.\d+|[一二三四五六七八九十]+、)"), 2),
        (re.compile(r"^(导论|绪论|附录[一二三四五六七八九十]?)"), 1)]


def full_ocr(page, dpi=130):
    pix = page.get_pixmap(dpi=dpi)
    arr = np.array(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return ocr_lib.ocr_lines(arr)


def footer_num(page, dpi=110):
    r = page.rect
    clip = fitz.Rect(r.x0, r.y0 + r.height * 0.90, r.x1, r.y1)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    arr = np.array(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    ls = ocr_lib.ocr_lines(arr)
    for ln in ls:
        m = re.search(r"(\d{1,3})\s*$", ln.strip())
        if m:
            return int(m.group(1))
    return None


def find_delta_by_title(rel, entries, toc_last):
    """标题锚定：取印刷页码最小的条目做锚，在其后 1~16 页全页 OCR 找标题"""
    if not entries:
        return None
    anchor = min(entries, key=lambda e: e[2])
    core = re.sub(r"^(第[一二三四五六七八九十百]+[章节篇]|Part\s*\d*|专题\s*\d+)", "", anchor[1])
    core = re.sub(r"[^一-龥A-Za-z]", "", core)[:8]
    if len(core) < 3:
        return None
    d = fitz.open(os.path.join(ROOT, *rel.split("/")))
    delta = None
    for p in range(toc_last + 1, min(toc_last + 17, d.page_count + 1)):
        try:
            ls = full_ocr(d.load_page(p - 1), dpi=90)
        except Exception:
            continue
        text = re.sub(r"\s+", "", "".join(ls))
        if core in text:
            delta = p - anchor[2]
            print(f"   (锚定: 『{anchor[1][:16]}』 印刷p{anchor[2]} -> PDF p{p}, delta={delta})", flush=True)
            break
    d.close()
    return delta


def parse(rel):
    v = SCAN[rel]
    toc_pages = v["toc_pages"]
    d = fitz.open(os.path.join(ROOT, *rel.split("/")))
    entries = []
    for p in toc_pages:
        for ln in full_ocr(d.load_page(p - 1)):
            s = re.sub(r"\s+", "", ln.strip())
            m = RE_ENTRY.match(s)
            if not m:
                continue
            title, pno = m.group(1), int(m.group(2))
            title = re.sub(r"^[·.·…]+|[·.·…]+$", "", title).strip("丨|")
            if len(title) < 2 or pno < 1 or pno > d.page_count + 60:
                continue
            lvl = 2
            for pat, lv in RANK:
                if pat.match(title):
                    lvl = lv
                    break
            entries.append((lvl, title, pno))
    # delta 校准：先页脚数字，失败则标题锚定
    start = max(toc_pages) + 1
    delta = None
    probes = []
    for p in range(start, min(start + 8, d.page_count)):
        n = footer_num(d.load_page(p - 1))
        probes.append((p, n))
        if n is not None and 1 <= n <= 50:
            delta = p - n
            break
    d.close()
    if delta is None and len(entries) >= 2:
        delta = find_delta_by_title(rel, entries, max(toc_pages))
    if delta is None and len(entries) >= 2:
        # delta 穷举：5~12，用最小页码条目验证
        d = fitz.open(os.path.join(ROOT, *rel.split("/")))
        anchor = min(entries, key=lambda e: e[2])
        core = re.sub(r"[^一-龥A-Za-z]", "", re.sub(
            r"^(第[一二三四五六七八九十百]+[章节篇]|Part\s*\d*|专题\s*\d+)", "", anchor[1]))[:6]
        for dv in range(4, 14):
            pg = anchor[2] + dv
            if pg > d.page_count:
                break
            try:
                ls = full_ocr(d.load_page(pg - 1), dpi=90)
            except Exception:
                continue
            text = re.sub(r"\s+", "", "".join(ls))
            if len(core) >= 3 and core in text:
                delta = dv
                print(f"   (穷举校准: delta={dv} 命中『{anchor[1][:16]}』)", flush=True)
                break
        d.close()
    return entries, delta, probes


EXCLUDE = ["配套词汇"]  # 双栏目录解析质量差，放弃自动写入
TARGETS = [rel for rel in SCAN if SCAN[rel]["toc_pages"] and not any(x in rel for x in EXCLUDE)]
if ONLY is not None:
    TARGETS = [r for r in TARGETS if ONLY in r]

for rel in TARGETS:
    entries, delta, probes = parse(rel)
    print(f"===== {rel.split('/')[-1]}  条目{len(entries)}  delta={delta}  探测={probes}", flush=True)
    for lvl, t, p in entries[:14]:
        pg = (p + delta) if delta is not None else p
        mark = "" if delta is not None else "!"
        print(f'   {"  "*(lvl-1)}p{pg:4d}{mark} {t[:36]}', flush=True)
    if not WRITE or delta is None or len(entries) < 2:
        continue
    if entries[0][0] != 1:
        entries = [(1,) + tuple(entries[0][1:])] + list(entries[1:])
    import fitz as F, shutil, datetime, hashlib
    fp = os.path.join(ROOT, *rel.split("/"))
    doc = F.open(fp)
    new_toc = []
    ll, lp = 0, 1
    for l, t, p in entries:
        l = min(l, ll + 1)
        pp = max(p + delta, lp)
        new_toc.append([l, t, pp])
        ll, lp = l, pp
    snap = {"file": rel, "old_toc": doc.get_toc(),
            "new_toc": new_toc,
            "time": datetime.datetime.now().strftime("%m-%d %H:%M")}
    json.dump(snap, open(os.path.join(HERE, "toc_snap_batch3", os.path.basename(fp) + ".mulu.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        doc.set_toc(new_toc)
    except ValueError as e:
        print(f"   !! set_toc失败 {e}，跳过", flush=True)
        doc.close()
        continue
    out = os.path.join(HERE, "_tmp_mulu.pdf")
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    shutil.move(out, fp)
    print("   >> 已写入", flush=True)
print("DONE", flush=True)
