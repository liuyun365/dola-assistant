#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_manager —— 提示词工作台（独立功能模块）。

仅通过 dola_connector 与豆啦啦通信，自身不负责底层通信；
左文档树 / 中分镜正文 / 右资产库+匹配 的 GUI 工作台，
后端用标准库 http.server，前端为 web/index.html 单页。
"""
from .parser import parse_shots, extract_asset_refs, norm_stem, read_text_file  # noqa: F401
from .matchers import auto_match, merge_match  # noqa: F401

__all__ = [
    "parse_shots", "extract_asset_refs", "norm_stem", "read_text_file",
    "auto_match", "merge_match",
]
