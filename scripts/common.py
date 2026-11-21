# -*- coding: utf-8 -*-
"""公共配置加载：所有脚本共享。

用法：
    默认读脚本同目录 config.json（不存在则用内置示例值）
    也可 --config / --root 命令行覆盖

config.json 字段：
    root               待处理 PDF 的根目录（空 = 当前工作目录）
    watermark_patterns 第三方导流/倒卖广告关键词（会被删除）
    protect_patterns   正版署名等受保护关键词（绝不删除，优先级高于水印）
    backup_dirname     原件 MD5 备份目录名（默认 _backup，放 root 下）
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG = {
    "root": "",
    "watermark_patterns": [
        "公众号", "小红书", "领取更多备考资料", "QQ群", " qq群",
        "添加微信", "低价购买", "一手资料", "免费领取", "加群",
    ],
    "protect_patterns": [],
    "backup_dirname": "_backup",
}


def load_config(path=None):
    cfg = dict(DEFAULT_CONFIG)
    p = path or os.path.join(HERE, "config.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            cfg[k] = v
    if not cfg.get("root"):
        cfg["root"] = os.getcwd()
    cfg["wm_re"] = re.compile("|".join(cfg["watermark_patterns"])) if cfg["watermark_patterns"] else None
    cfg["prot_re"] = re.compile("|".join(cfg["protect_patterns"])) if cfg["protect_patterns"] else None
    cfg["backup_dir"] = os.path.join(cfg["root"], cfg.get("backup_dirname", "_backup"))
    return cfg


def resolve(cfg, rel):
    """相对路径（正/反斜杠均可）-> root 下的绝对路径"""
    return os.path.join(cfg["root"], *rel.replace("\\", "/").split("/"))


def backup_file(cfg, src):
    """带 MD5 校验的原件备份，返回备份路径。"""
    import hashlib
    import shutil
    os.makedirs(cfg["backup_dir"], exist_ok=True)
    h = hashlib.md5(open(src, "rb").read()).hexdigest()[:10]
    dst = os.path.join(cfg["backup_dir"], f"{os.path.basename(src)}.{h}.bak")
    if not os.path.exists(dst):
        shutil.copy2(src, dst)
    return dst


def md5_of(path):
    import hashlib
    return hashlib.md5(open(path, "rb").read()).hexdigest()
