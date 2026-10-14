#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词解析与资产图匹配（纯业务逻辑，不依赖豆啦啦 API）."""
import os
import re
from pathlib import Path


def parse_prompts(text):
    """把提示词文件/文本解析成提示词列表。

    支持按 Markdown 标题(#/##/###)、分隔线(---)、序号(1. 2. 3.) 或空行分块。
    每个块取首行（若为短标题）作为 title，其余作为 prompt 正文。
    """
    if not text or not text.strip():
        return []
    raw = text.strip()

    # 用零宽 lookahead 在标题/分隔线前切分，保留标题文本
    parts = re.split(r"(?=\n\s*(?:#{1,3}\s+.*|-{3,})\s*\n)", raw)
    blocks = [p.strip() for p in parts if p and p.strip()]

    if len(blocks) <= 1:
        # 退路：按序号 1. 2. 3. 分块（前置 \n 以匹配行首序号）
        parts = re.split(r"\n\s*\d+[.、)]\s+", "\n" + raw)
        blocks = [p.strip() for p in parts if p and p.strip()]

    if len(blocks) <= 1:
        # 最后退路：按空行分段
        blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]

    items = []
    for i, b in enumerate(blocks):
        lines = b.split("\n")
        # 去掉开头的水平分隔线
        if lines and re.match(r"^-{3,}$", lines[0].strip()):
            lines = lines[1:]
            b = "\n".join(lines).strip()

        first = lines[0].strip() if lines else ""
        title = None
        body = b

        # 冒号内联小标题: "镜头三：雨夜..." -> 标题=镜头三, 正文=雨夜...
        colon_m = re.match(r"^(.{1,40})[：:]\s*(.*)$", first)
        if colon_m:
            title = colon_m.group(1).strip()
            rest = colon_m.group(2).strip()
            if len(lines) > 1:
                body = ((rest + "\n") if rest else "") + "\n".join(lines[1:]).strip()
            else:
                body = rest or first
        else:
            ends = ("。", ".", "！", "!", "？", "?", "，", ",", "；", ";")
            is_title = bool(first) and len(first) <= 40 and not first.endswith(ends)
            if is_title and len(lines) > 1:
                title = re.sub(r"^#{1,3}\s+", "", first)
                body = "\n".join(lines[1:]).strip() or first
            else:
                title = "提示词 %d" % (i + 1)
                body = b

        items.append({"title": title, "prompt": body})
    return items


def list_assets(asset_dir, exts=None):
    """列出资产图目录中支持的图片，按文件名排序."""
    if exts is None:
        exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
    if not asset_dir or not os.path.isdir(asset_dir):
        return []
    files = []
    for f in sorted(os.listdir(asset_dir)):
        if Path(f).suffix.lower() in exts:
            files.append(os.path.join(asset_dir, f))
    return files


def match_assets(prompts, assets):
    """按顺序把资产图匹配到提示词；资产数不足则后面的提示词无图."""
    return [
        {**p, "asset": assets[i] if i < len(assets) else None}
        for i, p in enumerate(prompts)
    ]
