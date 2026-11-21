# -*- coding: utf-8 -*-
"""全量盘点：递归列所有 PDF，记录 页数/书签数/文本层/权限/水印关键词命中
用法：python audit_pdfs.py [--config config.json] [--root DIR]
"""
import os, re, json, argparse
import fitz

from common import load_config

ap = argparse.ArgumentParser(description="PDF 批量盘点：书签/权限/水印")
ap.add_argument("--config", help="config.json 路径")
ap.add_argument("--root", help="覆盖 config 里的根目录")
ap.add_argument("--out", default="audit_result.json", help="输出 JSON 文件名")
args = ap.parse_args()

CFG = load_config(args.config)
if args.root:
    CFG["root"] = args.root
ROOTS = [CFG["root"]]
WM_PAT = CFG["wm_re"] or re.compile(r"$^")  # 无配置时不匹配

rows = []
for R in ROOTS:
    for dirpath, _, files in os.walk(R):
        for fn in sorted(files):
            if not fn.lower().endswith(".pdf"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                d = fitz.open(fp)
                n = d.page_count
                toc = d.get_toc()
                perm = d.permissions
                # 文本层抽样：前中后各3页
                txt, wmhit = 0, 0
                for i in range(0, n, max(1, n // 9)):
                    if i >= n:
                        break
                    t = d.load_page(i).get_text()
                    if len(t.strip()) > 80:
                        txt += 1
                    wmhit += len(WM_PAT.findall(t))
                d.close()
                rows.append({"rel": os.path.relpath(fp, os.path.dirname(R)),
                             "pages": n, "toc": len(toc), "perm": perm,
                             "txtpages": txt, "wmhit": wmhit,
                             "mb": round(os.path.getsize(fp) / 1048576, 1)})
            except Exception as e:
                rows.append({"rel": os.path.relpath(fp, os.path.dirname(R)),
                             "pages": -1, "toc": -1, "perm": 0,
                             "txtpages": 0, "wmhit": 0, "mb": 0, "err": str(e)[:60]})

json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  args.out), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

no_toc = [r for r in rows if r["toc"] == 0]
has_toc = [r for r in rows if r["toc"] > 0]
wm = [r for r in rows if r["wmhit"] > 0]
locked = [r for r in rows if r["perm"] not in (-1, -4, 0) and r["perm"] < -4]
print(f"总计 {len(rows)} 份 PDF")
print(f"  有书签 {len(has_toc)} 份 | 无书签 {len(no_toc)} 份 | 文本层水印命中 {len(wm)} 份 | 权限受限 {len(locked)} 份")
print("\n===== 无书签清单（需补）=====")
for r in no_toc:
    kind = "文本层" if r["txtpages"] >= 2 else ("扫描件" if r["txtpages"] == 0 else "半文本")
    print(f"  [{kind:4s}] {r['pages']:4d}p {r['mb']:6.1f}MB  {r['rel']}")
print("\n===== 文本层水印命中（需去）=====")
for r in wm:
    print(f"  hit={r['wmhit']:4d} {r['pages']:4d}p  {r['rel']}")
print("\n===== 权限受限 =====")
for r in locked:
    print(f"  perm={r['perm']} {r['rel']}")
