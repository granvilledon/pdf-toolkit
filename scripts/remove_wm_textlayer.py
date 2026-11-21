# -*- coding: utf-8 -*-
"""文本层水印删除 + 解除复制/编辑限制（不重排正文）

原理：按行级正则匹配水印文本 -> add_redact_annot（外扩±1px 盖抗锯齿边）
      -> apply_redactions(images=NONE, graphics=NONE, text=REMOVE) 只删字不动图
      -> save(encryption=PDF_ENCRYPT_NONE) 解权限锁，一步完成
      -> 重开成品自校验（统计水印残留页数）

用法：
    python remove_wm_textlayer.py <file1.pdf> [file2.pdf ...] [--config c.json] [--root DIR] [--out DIR]
    文件路径相对 --root（默认 config.root）；输出到 --out 目录（默认 wm_clean_out/）
"""
import os, re, argparse
import fitz

from common import load_config, resolve


def clean(src, dst, wm_re, prot_re=None):
    doc = fitz.open(src)
    removed_lines = 0
    pages_touched = 0
    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        targets = []
        for b in page.get_text("dict").get("blocks", []):
            for l in b.get("lines", []):
                txt = "".join(s.get("text", "") for s in l.get("spans", [])).strip()
                if not txt or not wm_re.search(txt):
                    continue
                if prot_re and prot_re.search(txt):
                    continue  # 受保护文本（正版署名等）绝不删除
                targets.append(fitz.Rect(l["bbox"]))
        if targets:
            pages_touched += 1
            for r in targets:
                page.add_redact_annot(r + (-1, -1, 1, 1))  # 略外扩覆盖抗锯齿边缘
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
            removed_lines += len(targets)
    doc.save(dst, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
    doc.close()
    # 自校验
    chk = fitz.open(dst)
    hit = sum(1 for i in range(chk.page_count) if wm_re.search(chk.load_page(i).get_text("text") or ""))
    perms = int(chk.permissions)
    npages = chk.page_count
    chk.close()
    return {"pages": npages, "pages_touched": pages_touched, "lines_removed": removed_lines,
            "new_perms": perms, "pages_still_with_watermark": hit,
            "src_size": os.path.getsize(src), "dst_size": os.path.getsize(dst)}


def main():
    ap = argparse.ArgumentParser(description="文本层水印删除 + 解权限锁（带自校验）")
    ap.add_argument("files", nargs="+", help="待处理 PDF（相对 --root）")
    ap.add_argument("--config", help="config.json 路径")
    ap.add_argument("--root", help="覆盖 config.root")
    ap.add_argument("--out", default="wm_clean_out", help="输出目录（相对当前目录）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.root:
        cfg["root"] = args.root
    wm_re = cfg["wm_re"] or re.compile(r"$^")
    prot_re = cfg.get("prot_re")
    os.makedirs(args.out, exist_ok=True)

    for rel in args.files:
        src = resolve(cfg, rel) if not os.path.isabs(rel) else rel
        name = os.path.basename(rel)
        r = clean(src, os.path.join(args.out, name), wm_re, prot_re)
        print(name)
        print("   ", r)
        if r["pages_still_with_watermark"]:
            print(f"    !! 仍有 {r['pages_still_with_watermark']} 页残留命中，需人工核查（可能是正文误报词）")


if __name__ == "__main__":
    main()
