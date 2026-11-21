<div align="center">

# 📚 PDF Toolkit

**扫描书 PDF 批处理工具集 —— 加书签目录 · 去水印 · 解权限锁 · 夜读化**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![PyMuPDF](https://img.shields.io/badge/Engine-PyMuPDF-red.svg)](https://pymupdf.readthedocs.io/)
[![OCR](https://img.shields.io/badge/OCR-RapidOCR-green.svg)](https://github.com/RapidAI/RapidOCR)

[简体中文](README.md) | [English](README_EN.md)

*实战战绩：150+ 本 PDF · 12.6 GB —— 书签 0 缺失 · 第三方水印清零 · 权限锁清零 · 夜读版全量生成*

![夜读化效果对比](docs/images/night-mode-comparison.png)

</div>

---

对**扫描版为主**的个人 PDF 库做四类批处理，纯本地运行，零外部服务。
**不绑定任何书籍**：目录、书单、水印规则全部走 `config.json` / 命令行参数。
README 与脚本中的示例均为合成样张，不含真实书籍内容。

## ✨ 四条管线

| 管线 | 一句话 | 入口 |
|---|---|---|
| 🔖 **加书签目录** | 文本层走 5 种版式规则引擎；扫描件走「大字分隔页检测 → 印刷目录 OCR → 页码校准」 | `add_toc_textlayer.py` / `detect_bigtitle_pages.py` → `add_toc_ocr_mulu.py` |
| 🧹 **去水印** | 文本层行级 redact（只删字不动图）；扫描件固定区域覆盖（正文密度闸门防误伤） | `remove_wm_textlayer.py` / `remove_wm_scan_cover.py` |
| 🔓 **解权限锁** | 抹字 + 解锁一步完成，重开文件自校验 | `remove_wm_batch.py` |
| 🌙 **夜读化** | 保色相反亮度：白纸→深灰底、黑字→亮灰字、彩色标注保留色相；书签页码全保留 | `night_pdf_batch.py` |

## ⚠️ 使用边界（先读这个）

只处理**个人自用文档**的三类干扰：

| ✅ 会处理 | ❌ 不会处理 |
|---|---|
| 第三方导流/倒卖广告水印（QQ群、微信号、"低价购买"） | 出版社/机构的**正版署名**（`protect_patterns` 保护组） |
| 复制/打印权限锁 | 任何 DRM 加密 |
| 书签缺失/结构错乱 | — |

判定规则写死在脚本里：**水印 = 跨页重复文本 + 位于页眉页脚**。正文里出现"微信公众号"（如题干引用）绝不能 redact——实战中真题题干就踩过这个雷。

## 🚀 快速开始

```bash
pip install -r requirements.txt
cp scripts/config.example.json scripts/config.json   # 改 root 和水印关键词

python scripts/audit_pdfs.py --root D:/my-pdfs                       # ① 盘点现状
python scripts/add_toc_textlayer.py --plan plan.json --root D:/my-pdfs   # ② 加目录（dry-run 默认）
python scripts/remove_wm_batch.py --dewm a.pdf --unlock b.pdf        # ③ 去水印/解锁（MD5 备份）
python scripts/night_pdf_batch.py --root D:/my-pdfs --limit 1        # ④ 夜读化（先试一本）
```

> 🛡️ 所有写盘操作：**dry-run 默认 + 旧状态快照 JSON + 原件 MD5 备份 + 映射表 CSV**，四件套齐了才动手；中断后再跑即续传。

## 🧰 脚本清单

| 脚本 | 功能 | 依赖 |
|---|---|---|
| `audit_pdfs.py` | 全量盘点：页数/书签/文本层/权限/水印命中 | PyMuPDF |
| `add_toc_textlayer.py` | 文本层批量加书签（5 种版式规则 + `toc_plan.json` 指派） | PyMuPDF |
| `detect_bigtitle_pages.py` | 扫描件大字分隔页检测（水平投影法） | PyMuPDF, numpy |
| `add_toc_ocr_mulu.py` | 印刷目录页 OCR 解析→页脚校准→书签 | PyMuPDF, RapidOCR |
| `remove_wm_textlayer.py` | 文本层水印 redact + 解锁 + 自校验 | PyMuPDF |
| `remove_wm_batch.py` | 批量去水印/解锁（`--dewm` / `--unlock` 分组，原地替换） | PyMuPDF |
| `remove_wm_scan_cover.py` | 扫描件页脚固定区域覆盖（密度闸门） | PyMuPDF, numpy |
| `night_pdf_batch.py` | 扫描书夜读化（自动发现、断点续传） | PyMuPDF, numpy, Pillow |
| `common.py` | 配置加载 / MD5 备份 / 路径解析 | — |
| `ocr_lib.py` | RapidOCR 封装（行级输出） | RapidOCR, pypdf |

<details>
<summary><b>🌙 夜读化原理（点击展开）</b></summary>

扫描版 PDF 没有文字层，阅读器的夜间模式全部无效。本工具直接改写每页嵌入图像：

- **保色相反亮度**：亮度通道 Y 反相映射到 `[lo, hi]`（默认 18~232），色度偏差 ×0.42 保留——白纸变深灰底、黑字变亮灰字、红蓝标注仍是红蓝
- **原地改写图像流**：`doc.update_stream(xref)` + `xref_set_key(...)`。⚠️ 不要用 `page.replace_image()`——它会新增对象留下旧图，文件双倍膨胀（实测踩坑）
- **体积优化**：灰度页自动转 `DeviceGray`；>2400px 的超大扫描图降采样重编码（26MP 原图 q85 会膨胀 2 倍，降采样后反而比原书小 60%）
- 实测 66 本 12.6 GB 全通过，书签/页面布局/页码零损失

</details>

## 💊 踩坑清单（比代码更值钱）

1. **水印误报是最大雷区**：正文词"购买/代理/微信公众号"会大量误报，必须「跨页重复 + 页眉页脚位置」双条件；扫描件水印**像素初筛 + 目视确认**两步走，条带相似度阈值法不可靠（某系列 25 本全部误报）。
2. **书签页码指向整页分隔页**，容差 1 页，≥2 页必须修；写入后全局页码必须单调不减。OCR 错字要人工对照表修正（如 `读职罪→渎职罪`、`第——编→第一编`），标题以**书面印刷字**为准。
3. **无结构锚点的书不要硬造目录**（回忆版真题直接跳过）；质量闸门（页眉覆盖率 <40% 跳过）比事后返工便宜。
4. **凡是改文件的操作**：dry-run 默认 + 旧状态快照 JSON + 原件 MD5 备份 + 映射表 CSV。
5. `apply_redactions` 是 **Page** 方法不是 Document 方法；`exec` 注入脚本要补 `__file__`。
6. `page.replace_image()` 新增对象不替换，孤儿旧图让体积翻倍；用 `update_stream + xref_set_key` 原地改写。
7. 权限锁判断用 `doc.permissions`，解锁后必须重开文件验证（`PDF_ENCRYPT_NONE` 只在 save 时生效）。

## 📄 深度文档

- [`docs/加目录标准-v2.md`](docs/加目录标准-v2.md) — 书签层级/页码/标题完整规范（Project MUSE 出版规范本地化版）：层级总表、整页分隔页规则、容差、OCR 错字对照

## License

[MIT](LICENSE)
