#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词推送功能模块.

建立在 dola_connector 之上，把"提示词 + 资产图"批量填入豆啦啦实例。
本模块不接触豆啦啦 API 细节，只通过连接器通信。
"""
from .parser import parse_prompts, list_assets, match_assets
from .service import prepare, push_items

__all__ = [
    "parse_prompts", "list_assets", "match_assets",
    "prepare", "push_items",
]
__version__ = "1.0.0"
