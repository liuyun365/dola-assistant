#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词推送的编排逻辑（建立在 dola_connector 之上）.

本模块负责"解析提示词 -> 匹配资产 -> 逐条填入当前实例"，
不关心豆啦啦 API 细节，只调用 DolaConnector 暴露的接口。
"""
import time
from typing import Callable, Dict, List, Optional

from dola_connector import DolaConnector
from .parser import parse_prompts, list_assets, match_assets


def prepare(prompt_text: str, asset_dir: Optional[str]):
    """解析提示词并匹配资产图，返回 (prompts, assets, items)。

    items: [{title, prompt, asset?}, ...]，asset 为本地图片绝对路径或 None。
    """
    prompts = parse_prompts(prompt_text)
    assets = list_assets(asset_dir) if asset_dir else []
    items = match_assets(prompts, assets)
    return prompts, assets, items


def push_items(connector: DolaConnector, items: List[Dict], *,
               auto_send: bool = False, delay: float = 6,
               wait_manual: bool = False,
               on_log: Optional[Callable] = None,
               on_progress: Optional[Callable] = None) -> List[Dict]:
    """逐条把提示词 + 资产填入当前实例。

    参数:
      items:        [{title, prompt, asset?}, ...]
      auto_send:    是否自动发送/生成
      delay:        不自动发送时每条之间的等待秒数
      wait_manual:  不自动发送时，每条等终端按回车再继续（适合逐条点生成）
      on_log:       日志回调(msg)
      on_progress:  进度回调(cur, total, title, status)
    """
    results: List[Dict] = []
    total = len(items)
    for i, item in enumerate(items):
        title = item.get("title", f"第{i + 1}条")
        if on_log:
            on_log(f"[{i + 1}/{total}] {title}")
        try:
            connector.paste_text(item["prompt"])
            if item.get("asset"):
                connector.paste_images([item["asset"]])
                time.sleep(0.6)  # 给输入框一点缓冲，避免图还没贴上就被覆盖

            if auto_send:
                connector.send()
                status = "已发送"
                if delay > 0:
                    time.sleep(delay)
            else:
                status = "已填入"

            if on_progress:
                on_progress(i + 1, total, title, status)
            results.append({"index": i, "title": title, "ok": True})
        except Exception as e:
            if on_progress:
                on_progress(i + 1, total, title, f"error: {e}")
            results.append({"index": i, "title": title, "ok": False, "error": str(e)})

        # 多条目且"只填不发送"时，等待用户手动点生成再继续
        if i < total - 1 and not auto_send:
            if wait_manual:
                if on_log:
                    on_log("请在豆啦啦中点【生成】，然后按回车继续下一条...")
                input("按回车继续 >> ")
            elif delay > 0:
                if on_log:
                    on_log(f"请在 {delay}s 内点【生成】，之后自动继续...")
                time.sleep(delay)
    return results
