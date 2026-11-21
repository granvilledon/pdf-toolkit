# -*- coding: utf-8 -*-
"""
扫描版 PDF 夜读化（C 方案：高对比）
- 原地替换页面图像流：书签 / 页面布局 / 页码全部保留
- 保色相反亮度：正文变浅灰底深灰字，彩色标注只压暗不改色相
- 已存在输出则跳过，可断点续传
用法：
    python night_pdf_batch.py            # 处理全部
    python night_pdf_batch.py --limit 1  # 只处理第一本（试跑）
"""
import io, os, sys, json, time, traceback
import numpy as np
import pymupdf as fitz
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# ---- C 方案参数（高对比）----
LO, HI, CHROMA = 18, 232, 0.42
Q = 85
SCALE_MAX_EDGE = 2400   # 超大扫描图（>2400）缩到此长边，q82；阅读完全够用且体积大降
SCALE_Q = 82
SUFFIX = "-夜读版"

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "progress.log")


def is_gray(arr):
    s = arr[::8, ::8].astype(np.int16)
    return float((s.max(axis=2) - s.min(axis=2)).mean()) < 8.0


def has_dup_images(path):
    """检测旧版双图残留（replace_image 会新增对象留下旧图，n_img≈2×页数）"""
    try:
        d = fitz.open(path)
    except Exception:
        return False
    n_img = 0
    for x in range(1, d.xref_length()):
        try:
            if d.xref_get_key(x, "Subtype")[1] == "/Image":
                n_img += 1
        except Exception:
            pass
    n = d.page_count
    d.close()
    return n_img > n * 1.15


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def night(arr):
    """保色相反亮度：Y 反相映射到 [LO,HI]，色度按 CHROMA 衰减"""
    a = arr.astype(np.float32)
    y = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    yn = np.clip(y * (1.0 / 255.0), 0.0, 1.0)
    yt = LO + (1.0 - yn) * (HI - LO)
    d = (a - y[..., None]) * CHROMA
    return np.clip(yt[..., None] + d, 0, 255).astype(np.uint8)


def process_page(doc, page):
    imgs = page.get_images(full=True)
    if not imgs:
        return False
    # 取覆盖面积最大的那张（扫描件通常是整页单图）
    area_max, target = -1, None
    prect = page.rect
    parea = prect.width * prect.height or 1
    for im in imgs:
        xref = im[0]
        for r in page.get_image_rects(xref):
            a = abs(r.width * r.height) / parea
            if a > area_max:
                area_max, target = a, xref
    if target is None or area_max < 0.4:
        return False

    meta = doc.extract_image(target)
    try:
        im = Image.open(io.BytesIO(meta["image"]))
        im.load()
    except Exception:
        # 兜底：直接渲染页面
        pix = page.get_pixmap(dpi=200)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    gray_src = (im.mode in ("L", "1"))
    rgb = im.convert("RGB")
    arr = np.asarray(rgb)
    out = night(arr)

    gray = gray_src or is_gray(arr)
    if gray:
        # 亮度即灰度值，加权转 L 保证与视觉一致
        g = (0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2])
        img_out = Image.fromarray(np.clip(g + 0.5, 0, 255).astype(np.uint8), mode="L")
        cs = "/DeviceGray"
    else:
        img_out = Image.fromarray(out)
        cs = "/DeviceRGB"

    q = Q
    if max(img_out.size) > SCALE_MAX_EDGE:
        r = SCALE_MAX_EDGE / max(img_out.size)
        img_out = img_out.resize((round(img_out.width * r), round(img_out.height * r)), Image.LANCZOS)
        q = SCALE_Q

    buf = io.BytesIO()
    img_out.save(buf, format="JPEG", quality=q, optimize=False)
    data = buf.getvalue()
    # 原地改写原图像对象（不新增对象，避免旧图残留导致体积翻倍）
    doc.update_stream(target, data, compress=False)
    doc.xref_set_key(target, "Filter", "/DCTDecode")
    doc.xref_set_key(target, "ColorSpace", cs)
    doc.xref_set_key(target, "BitsPerComponent", "8")
    doc.xref_set_key(target, "DecodeParms", "null")
    doc.xref_set_key(target, "Decode", "null")
    return True


def process_book(path):
    dst = path.replace(".pdf", SUFFIX + ".pdf")
    if os.path.exists(dst):
        if has_dup_images(dst):
            os.remove(dst)
            log(f"旧版含双图残留（体积翻倍），已删除重跑：{os.path.basename(dst)}")
        else:
            log(f"跳过（已存在且干净）：{os.path.basename(dst)}")
            return "skip"
    t0 = time.time()
    doc = fitz.open(path)
    n = doc.page_count
    toc_before = len(doc.get_toc())
    done = 0
    for i in range(n):
        try:
            if process_page(doc, doc[i]):
                done += 1
        except Exception as e:
            log(f"   页 {i+1} 失败（跳过）：{type(e).__name__} {e}")
        if (i + 1) % 50 == 0:
            el = time.time() - t0
            log(f"   ... {i+1}/{n} 页，{el:.0f}s，预计剩余 {el/(i+1)*(n-i-1)/60:.1f} 分钟")
    tmp = dst + ".part"
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    os.replace(tmp, dst)
    toc_after = len(fitz.open(dst).get_toc())
    mb_o = os.path.getsize(path) / 1048576
    mb_n = os.path.getsize(dst) / 1048576
    log(f"完成：{os.path.basename(dst)} | {n}页/{done}页已改 | {mb_o:.0f}MB→{mb_n:.0f}MB "
        f"| 书签 {toc_before}→{toc_after} | 耗时 {(time.time()-t0)/60:.1f} 分钟")
    return "ok"


def discover(root):
    """递归收集待处理 PDF（跳过夜读版自身与备份目录），按体积降序"""
    out = []
    skip_dirs = {SUFFIX.strip("-"), "_backup", "wm_clean_out"}
    for dp, dn, fn in os.walk(root):
        if any(s in dp for s in skip_dirs):
            continue
        for f in sorted(fn):
            if f.lower().endswith(".pdf") and SUFFIX not in f:
                p = os.path.join(dp, f)
                out.append((p, os.path.getsize(p)))
    return [p for p, _ in sorted(out, key=lambda x: -x[1])]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="扫描版 PDF 批量夜读化（断点续传）")
    ap.add_argument("--root", help="PDF 根目录（默认当前目录）")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 本（试跑）")
    args = ap.parse_args()
    root = args.root or os.getcwd()
    targets = discover(root)
    log(f"===== 开始：{len(targets)} 本，C 方案 lo={LO} hi={HI} chroma={CHROMA} q={Q} =====")
    ok = fail = skip = 0
    for k, p in enumerate(targets):
        if args.limit is not None and k >= args.limit:
            break
        log(f"[{k+1}/{len(targets)}] {os.path.basename(p)} ({os.path.getsize(p)/1048576:.0f}MB)")
        try:
            r = process_book(p)
            if r == "ok": ok += 1
            elif r == "skip": skip += 1
        except Exception as e:
            fail += 1
            log(f"  失败：{type(e).__name__} {e}")
            log(traceback.format_exc()[-500:])
    log(f"===== 结束：成功 {ok}，跳过 {skip}，失败 {fail} =====")


if __name__ == "__main__":
    main()
