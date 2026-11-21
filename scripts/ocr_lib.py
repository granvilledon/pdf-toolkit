# -*- coding: utf-8 -*-
"""扫描件 OCR 工具（只读管线，无副作用）"""
import io, re, os
import numpy as np
from PIL import Image
from pypdf import PdfReader
from rapidocr_onnxruntime import RapidOCR

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RapidOCR()
    return _ENGINE


def page_image(page, scale=1.0, crop=None):
    objs = page.images
    if not objs:
        return None
    img = Image.open(io.BytesIO(objs[0].data)).convert("RGB")
    w, h = img.size
    if crop:
        img = img.crop((0, 0, w, int(h * crop)))
    if scale != 1.0:
        w, h = img.size
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return np.array(img)


def ocr_lines(arr, tol=14):
    """OCR → 按 y 聚合成行文本列表"""
    res, _ = engine()(arr)
    if not res:
        return []
    boxes = []
    for box, txt, score in res:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append((min(ys), max(ys), min(xs), txt))
    boxes.sort(key=lambda b: b[0])
    lines, cur = [], []
    last = None
    for y0, y1, x0, txt in boxes:
        if last is None or abs(y0 - last) <= tol:
            cur.append((x0, txt))
        else:
            lines.append("".join(t for _, t in sorted(cur)))
            cur = [(x0, txt)]
        last = y0
    if cur:
        lines.append("".join(t for _, t in sorted(cur)))
    return lines
