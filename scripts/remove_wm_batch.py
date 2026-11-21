# -*- coding: utf-8 -*-
"""批量去水印 + 解权限锁（原地替换，MD5 备份可回滚，带三重校验）

用法：
    python remove_wm_batch.py --dewm a.pdf b.pdf --unlock c.pdf ... [--config c.json] [--root DIR]
    --dewm   删除水印 + 解锁（第三方导流/倒卖广告）
    --unlock 仅解除权限锁，不动内容（正版机构署名按此处理）
    路径相对 --root。校验不过（页数变/水印残留/权限未解）自动跳过该文件。
"""
import os, re, csv, hashlib, shutil, datetime, argparse
import fitz

from common import load_config, resolve, md5_of

ap = argparse.ArgumentParser(description="批量去水印/解锁（原地替换 + MD5 备份）")
ap.add_argument("--dewm", nargs="*", default=[], help="要删除水印+解锁的文件")
ap.add_argument("--unlock", nargs="*", default=[], help="仅解锁的文件")
ap.add_argument("--config")
ap.add_argument("--root")
args = ap.parse_args()

CFG = load_config(args.config)
if args.root:
    CFG["root"] = args.root
PAT = CFG["wm_re"] or re.compile(r"$^")
PROT = CFG.get("prot_re")
BAK = CFG["backup_dir"]
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_clean2")
os.makedirs(BAK, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

def strip_wm(src, dst):
    doc = fitz.open(src)
    n = doc.page_count
    touched = 0
    for i in range(n):
        page = doc.load_page(i)
        d = page.get_text("dict")
        rects = []
        for b in d.get("blocks", []):
            for l in b.get("lines", []):
                t = "".join(s.get("text", "") for s in l.get("spans", [])).strip()
                if t and PAT.search(t) and not (PROT and PROT.search(t)):
                    rects.append(fitz.Rect(l["bbox"]))
        if rects:
            touched += 1
            for r in rects:
                page.add_redact_annot(r + (-1, -1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
    doc.save(dst, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
    doc.close()
    return n, touched

def unlock_only(src, dst):
    doc = fitz.open(src)
    n = doc.page_count
    doc.save(dst, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
    doc.close()
    return n

rows = []
for rel in args.dewm:
    src = resolve(CFG, rel) if not os.path.isabs(rel) else rel
    name = os.path.basename(rel)
    tmp = os.path.join(TMP, name)
    src_md5, src_size = md5(src), os.path.getsize(src)
    n, touched = strip_wm(src, tmp)
    chk = fitz.open(tmp)
    npages = chk.page_count
    hits = sum(1 for i in range(npages) if PAT.search(chk.load_page(i).get_text("text") or ""))
    perms = int(chk.permissions)
    head = (chk.load_page(0).get_text("text") or "")[:70].replace("\n", " ")
    chk.close()
    ok = (npages == n and hits == 0 and perms == -4)
    print(f'[去水印] {name}: {n}页 → {npages}页, 抹水印页={touched}, 残留={hits}, perms={perms}, OK={ok}')
    print(f'         首页: {head}')
    if not ok:
        print('   !! 校验未过，跳过'); continue
    bak = os.path.join(BAK, name)
    shutil.move(src, bak); shutil.move(tmp, src)
    assert md5(bak) == src_md5
    rows.append({"处理": "去水印", "文件名": name, "恢复目标": rel, "MD5": src_md5,
                 "原KB": src_size // 1024, "新KB": os.path.getsize(src) // 1024,
                 "页数": npages, "时间": datetime.datetime.now().strftime("%m-%d %H:%M")})

for rel in args.unlock:
    src = resolve(CFG, rel) if not os.path.isabs(rel) else rel
    name = os.path.basename(rel)
    tmp = os.path.join(TMP, name)
    src_md5, src_size = md5(src), os.path.getsize(src)
    n = unlock_only(src, tmp)
    chk = fitz.open(tmp)
    npages = chk.page_count
    perms = int(chk.permissions)
    chk.close()
    ok = (npages == n and perms == -4)
    print(f'[解锁] {name}: {n}页 → {npages}页, perms={perms}, OK={ok}')
    if not ok:
        print('   !! 跳过'); continue
    bak = os.path.join(BAK, name)
    shutil.move(src, bak); shutil.move(tmp, src)
    assert md5(bak) == src_md5
    rows.append({"处理": "仅解锁", "文件名": name, "恢复目标": rel, "MD5": src_md5,
                 "原KB": src_size // 1024, "新KB": os.path.getsize(src) // 1024,
                 "页数": npages, "时间": datetime.datetime.now().strftime("%m-%d %H:%M")})

csvp = os.path.join(BAK, "000-去水印映射表-可回滚.csv")
if rows:
    with open(csvp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
print("\n完成", len(rows), "份；映射表", csvp)
