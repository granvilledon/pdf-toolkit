# -*- coding: utf-8 -*-
"""文本层批量加目录（规则引擎版）

按「版式规则」为有文字层的 PDF 生成书签：内置 5 种规则——
  shijuan  真题试卷：页眉课别状态机 + 正文题型行（时间线交错合并）
  huayan   答案解析：题型行两次轮换切分基础/综合课
  jiedu    章节题集：章 L1 + 节 L2，同章去重
  minfa    多编循环：章号回退=新编开始，编名取页首行
  1000ti   页眉「第X部分·题型」状态机 + 覆盖率质量闸门
自定义规则：仿照这些函数写正则状态机即可接入。

用法：
    python add_toc_textlayer.py --plan toc_plan.json [--config c.json] [--write]
    toc_plan.json: {"items": [{"file": "相对路径", "rule": "shijuan|huayan|jiedu|minfa|1000ti|null"}]}
    dry-run 默认；--write 写盘（旧书签自动快照到 toc_snap/，可回滚）。
"""
import os, re, sys, json, shutil, datetime, argparse
import fitz

ap = argparse.ArgumentParser(description="文本层 PDF 批量加书签（dry-run 默认）")
ap.add_argument("--plan", required=True, help="toc_plan.json 路径")
ap.add_argument("--config", help="config.json（提供 root）")
ap.add_argument("--root", help="覆盖根目录")
ap.add_argument("--write", action="store_true", help="写盘（默认 dry-run）")
args = ap.parse_args()
WRITE = args.write

from common import load_config, resolve
CFG = load_config(args.config)
if args.root:
    CFG["root"] = args.root
ROOT = CFG["root"]
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "toc_snap")
os.makedirs(SNAP, exist_ok=True)

RE_KE = re.compile(r"^(专业基础课|专业综合课)")
RE_TIXING = re.compile(r"^(一|二|三|四|五|六|七)\s*、\s*(单项选择题|多项选择题|简答题|辨析题|法条分析题|案例分析题|分析题|论述题)")
RE_CHAP = re.compile(r"^(第[一二三四五六七八九十百]+章)\s*(.*)$")
RE_SEC = re.compile(r"^([一二三四五六七八九十]+)\s*、\s*(.{2,24})$")
RE_1000 = re.compile(r"^第([一二三四五])部分\s*(.*?)(?:[·，,]\s*)?(单项选择题|多项选择题|分析题|简答题)?\s*$")
SUBJECT = {"一": "马克思主义基本原理", "二": "毛泽东思想和中国特色社会主义理论体系概论",
           "三": "中国近现代史纲要", "四": "思想道德与法治", "五": "形势与政策以及当代世界经济与政治"}


def toc_shijuan(rel):
    """真题试卷：页眉课别状态机 + 正文题型行"""
    d = fitz.open(os.path.join(ROOT, *rel.split("/")))
    ke_seq = []   # (页, 课别)
    tx = []       # (页, 题型)
    for i in range(d.page_count):
        lines = [l.strip() for l in d.load_page(i).get_text().split("\n") if l.strip()]
        head = lines[:3]
        for ln in head:
            m = RE_KE.match(ln)
            if m:
                if not ke_seq or ke_seq[-1][1] != m.group(1):
                    ke_seq.append((i + 1, m.group(1)))
                break
        for ln in lines:
            m = RE_TIXING.match(ln)
            if m and "·第" not in ln and len(ln) < 40:
                if not tx or tx[-1][1] != m.group(0):
                    tx.append((i + 1, m.group(0)))
    d.close()
    # 课别序列：基础→综合→基础(速查)→综合(速查)
    ke_label = []   # (页, 标签)
    counter = {}
    for pg, ke in ke_seq:
        counter[ke] = counter.get(ke, 0) + 1
        label = ke if counter[ke] == 1 else f"答案速查·{ke}"
        ke_label.append((pg, label))
    # 时间线交错：页排序后 课别L1 / 题型L2
    events = [(pg, 0, lab) for pg, lab in ke_label] + [(pg, 1, t) for pg, t in tx]
    events.sort(key=lambda x: (x[0], x[1]))
    toc, seen = [], set()
    last_lvl, last_p = 0, 1
    for pg, _, t in events:
        lvl = 1 if t.startswith("专业") or t.startswith("答案速查") else 2
        lvl = min(lvl, last_lvl + 1)
        key = (lvl, t, pg)
        if t not in seen or lvl == 1:
            if (t, pg) in seen:
                continue
            seen.add((t, pg))
            pg2 = max(pg, last_p)
            toc.append((lvl, t, pg2))
            last_lvl, last_p = lvl, pg2
    return toc


def toc_huayan(rel):
    """答案解析册：题型行两次轮换切分基础/综合课"""
    d = fitz.open(os.path.join(ROOT, *rel.split("/")))
    tx = []
    for i in range(d.page_count):
        for ln in d.load_page(i).get_text().split("\n"):
            s = ln.strip()
            m = RE_TIXING.match(s)
            if m and len(s) < 40:
                if not tx or tx[-1][1] != m.group(0):
                    tx.append((i + 1, m.group(0)))
    d.close()
    first = {}
    for pg, t in tx:
        m = RE_TIXING.match(t)
        first.setdefault(m.group(1) + m.group(2), pg)
    # 「一、单项选择题」第二次出现 = 综合课
    second = None
    cnt = 0
    for pg, t in tx:
        m = RE_TIXING.match(t)
        if m.group(1) == "一" and m.group(2) == "单项选择题":
            cnt += 1
            if cnt == 2:
                second = pg
                break
    toc = [(1, "专业基础课", 1)]
    for pg, t in tx:
        if second and pg >= second:
            break
        toc.append((2, t, pg))
    if second:
        toc.append((1, "专业综合课", second))
        for pg, t in tx:
            if pg >= second:
                toc.append((2, t, pg))
    return toc


def toc_jiedu(rel):
    """章节题集：章 L1 + 节 L2"""
    d = fitz.open(os.path.join(ROOT, *rel.split("/")))
    toc = []
    for i in range(d.page_count):
        for ln in d.load_page(i).get_text().split("\n"):
            s = ln.strip()
            m = RE_CHAP.match(s)
            if m and len(s) <= 30:
                title = s if len(s) > len(m.group(1)) + 1 else ""
                toc.append((1, m.group(1), i + 1))
                continue
            m = RE_SEC.match(s)
            if m and len(s) <= 32:
                toc.append((2, s, i + 1))
    d.close()
    # 去重（同章名重复取首现）
    seen, out = set(), []
    for lvl, t, pg in toc:
        if t in seen:
            continue
        seen.add(t)
        out.append((lvl, t, pg))
    return out


def toc_minfa(rel):
    """多编循环题集（如民法典分编）：多编循环结构。章号回退=新编开始，编名取该页首行原文"""
    d = fitz.open(os.path.join(ROOT, *rel.split("/")))
    toc, last_no, cur_parent = [], 0, None
    CLEAN = re.compile(r"[©O0。ｏＯ]")
    for i in range(d.page_count):
        lines = [l.strip() for l in d.load_page(i).get_text().split("\n") if l.strip()]
        chapter = None
        for ln in lines[:3]:
            m = re.match(r"^(第[一二三四五六七八九十百]+章)\s*(.*)$", ln)
            if m:
                name = CLEAN.sub("", m.group(2)).strip()
                chapter = (m.group(1), name)
                break
        if not chapter:
            continue
        no = chapter[0]
        num = "一二三四五六七八九十百".find(no[1])  # 粗序
        if num < last_no:  # 章号回退 => 新编
            bian = None
            for ln in lines[:4]:
                mApp = re.match(r"^(附录[一二三四五六七八九十]+[^©O0。]{0,20})", ln)
                if mApp:
                    bian = CLEAN.sub("", mApp.group(1)).strip()
                    break
                if not re.match(r"^(第[一二三四五六七八九十百]+章|[一〇〇一二三四五六七八九十]+、|[A-D]\.|［|\d)", ln) and 2 <= len(ln) <= 12:
                    bian = CLEAN.sub("", ln).strip()
                    break
            if bian and (not toc or toc[-1][1] != bian):
                toc.append((1, bian, i + 1))
                cur_parent = 1
        last_no = num
        label = chapter[0] + ("　" + chapter[1] if chapter[1] else "")
        # 同编内同章去重：找最近一个 L1/L2 之前的同名章
        dup = False
        for j in range(len(toc) - 1, -1, -1):
            if toc[j][0] <= 1:
                break
            if toc[j][0] == 2 and toc[j][1] == label:
                dup = True
                break
        if not dup and (not toc or toc[-1][1] != label):
            toc.append((2, label, i + 1))
        for ln in lines[:4]:
            m = re.match(r"^([一二三四五六七八九十]+)、(客观题|主观题|简答题|法条分析题|案例分析题|论述题)\s*$", ln)
            if m:
                t = f"{m.group(1)}、{m.group(2)}"
                if not toc or toc[-1][1] != t:
                    toc.append((3, t, i + 1))
                break
    d.close()
    if toc and toc[0][0] == 2:  # 首项是章 => 前面补第一编名（取p1首个非章/节/选项行）
        d = fitz.open(os.path.join(ROOT, *rel.split("/")))
        first = d.load_page(0).get_text().split("\n")
        d.close()
        bian = None
        for ln in first:
            s = CLEAN.sub("", ln.strip())
            if s and not re.match(r"^(第[一二三四五六七八九十百]+章|[一二三四五六七八九十]+、|[A-DＡ-Ｚ]|\d|［|（)", s) and 2 <= len(s) <= 12:
                bian = s
                break
        toc.insert(0, (1, bian or "总则", 1))
    return toc


def toc_1000(rel):
    """页眉科目题集：「第X部分科目·题型」状态机"""
    d = fitz.open(os.path.join(ROOT, *rel.split("/")))
    toc, last_ke, last_tx = [], None, None
    covered, npages = 0, d.page_count
    for i in range(d.page_count):
        lines = [l.strip() for l in d.load_page(i).get_text().split("\n") if l.strip()]
        for ln in lines[:3]:
            m = RE_1000.match(ln)
            if m and m.group(1) in SUBJECT:
                covered += 1
                if last_ke != m.group(1):
                    last_ke = m.group(1)
                    toc.append((1, f"第{last_ke}部分 {SUBJECT[last_ke]}", i + 1))
                tx = m.group(3)
                if tx and last_tx != tx:
                    last_tx = tx
                    toc.append((2, tx, i + 1))
                break
    d.close()
    return toc, covered, npages


BUILDERS = {"shijuan": toc_shijuan, "huayan": toc_huayan, "jiedu": toc_jiedu,
            "minfa": toc_minfa, "1000ti": toc_1000}

plan = json.load(open(args.plan, encoding="utf-8"))
items = plan.get("items", plan if isinstance(plan, list) else [])
written, skipped = [], []
for item in items:
    rel = item["file"].replace("\\", "/")
    rule = item.get("rule")
    if not rule:
        print(f"===== {rel} -> 无规则（无结构锚点），跳过", flush=True)
        skipped.append(rel)
        continue
    builder = BUILDERS.get(rule)
    if builder is None:
        print(f"===== {rel} -> 未知规则 {rule}，跳过", flush=True)
        skipped.append(rel)
        continue
    fp = resolve(CFG, rel)
    if not os.path.exists(fp):
        print(f"===== {rel} -> 文件不存在，跳过", flush=True)
        skipped.append(rel)
        continue
    try:
        res = builder(rel)
        toc = res[0] if isinstance(res, tuple) else res
        covered = res[1] if isinstance(res, tuple) and len(res) > 1 else None
        npages = res[2] if isinstance(res, tuple) and len(res) > 2 else None
    except Exception as e:
        print(f"===== {rel} 异常 {e}", flush=True)
        skipped.append(rel)
        continue
    n_real = len(toc)
    print(f"===== {rel} -> {n_real} 条", flush=True)
    for lvl, t, pg in toc[:16]:
        print(f'   {"  "*(lvl-1)}p{pg:4d} {t}', flush=True)
    if covered is not None:
        print(f"   (页眉覆盖 {covered}/{npages})", flush=True)
        if covered < npages * 0.4:
            print("   !! 页眉覆盖不足40%，跳过", flush=True)
            skipped.append(rel)
            continue
    if n_real < 2:
        print("   !! 条目<2，跳过", flush=True)
        skipped.append(rel)
        continue
    if not WRITE:
        continue
    fp = os.path.join(ROOT, *rel.split("/"))
    doc = fitz.open(fp)
    snap = {"file": rel, "old_toc": doc.get_toc(), "new_toc": [list(x) for x in toc],
            "time": datetime.datetime.now().strftime("%m-%d %H:%M")}
    json.dump(snap, open(os.path.join(SNAP, os.path.basename(rel) + ".toc.json"), "w",
              encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        doc.set_toc(toc)
    except ValueError as e:
        print(f"   !! set_toc失败: {e}；首条: {toc[:3]}", flush=True)
        skipped.append(rel)
        doc.close()
        continue
    out = os.path.join(HERE, "_tmp_toc3.pdf")
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    shutil.move(out, fp)
    written.append(rel)
    print("   >> 已写入", flush=True)

print("written:", len(written), " skipped:", len(skipped), flush=True)
print("DONE", "WRITE" if WRITE else "DRY-RUN", flush=True)
