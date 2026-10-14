#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词推送命令行入口。

通过 dola_connector 与豆啦啦通信：把提示词 + 资产图填到指定 Dola 实例。
默认只填入、不发送；生成按钮由你在豆啦啦里自己点（加 --send 才自动发送）。

纯标准库，无第三方依赖。
"""
import argparse
import os
import sys

# 项目根目录（本文件的上上级）加入 sys.path，使 dola_connector / prompt_pusher 可导入
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dola_connector import DolaConnector
from dola_connector.config import DEFAULT_API_URL
from prompt_pusher.service import prepare, push_items


def read_text(path):
    """读文本，依次尝试 utf-8 / gbk / gb2312。"""
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="推送提示词+资产图到豆啦啦 Dola 实例（默认仅填入，不发送）")
    parser.add_argument("prompt_file", nargs="?", help="提示词文件(.md/.txt)")
    parser.add_argument("--asset-dir", "-a", help="资产图文件夹")
    parser.add_argument("--api-url", "-c", default=DEFAULT_API_URL,
                        help="豆啦啦本地 API 地址 (默认 http://127.0.0.1:17823)")
    parser.add_argument("--instance", "-i",
                        help="指定实例：序号(1-based) 或 实例id/名称(如 Dola-32)")
    parser.add_argument("--list-instances", action="store_true",
                        help="只列出当前所有实例后退出")
    parser.add_argument("--send", action="store_true",
                        help="自动发送/生成（默认仅填入，不发送）")
    parser.add_argument("--delay", "-d", type=float, default=6,
                        help="不自动发送时每条之间的等待秒数(默认6)")
    parser.add_argument("--wait-manual", action="store_true",
                        help="不自动发送时，每条等你在终端按回车再继续")
    parser.add_argument("--dry-run", action="store_true",
                        help="只解析并打印匹配，不推送")
    args = parser.parse_args()

    connector = DolaConnector(api_url=args.api_url)
    try:
        instances = connector.list_instances()
    except Exception as e:
        print(f"连接失败: {e}")
        return 1

    # 列出实例
    if args.list_instances:
        print(f"当前实例 (共 {len(instances)} 个):")
        for idx, it in enumerate(instances):
            print(f"  [{idx + 1}] {it}")
        return 0

    # 选择实例
    try:
        if args.instance:
            target = connector.ensure_instance(args.instance)
            print(f"已切换到实例: {target.id} (名称={target.name})")
        else:
            target = connector.pick_default_instance()
            print(f"目标实例: {target.id} (名称={target.name})"
                  f"  —— 可用 --instance <序号|名称> 指定其他实例。")
    except Exception as e:
        print(f"选择实例失败: {e}")
        return 1

    if not args.prompt_file:
        print("未提供提示词文件。用法: cli.py 提示词.md -a 资产图目录 [--instance Dola-32]")
        return 1
    if not os.path.isfile(args.prompt_file):
        print(f"提示词文件不存在: {args.prompt_file}")
        return 1

    text = read_text(args.prompt_file)
    prompts, assets, items = prepare(text, args.asset_dir)
    if not prompts:
        print("未解析到任何提示词")
        return 1

    print(f"\n解析到 {len(prompts)} 条提示词，{len(assets)} 张资产图")
    for i, it in enumerate(items):
        asset_name = os.path.basename(it["asset"]) if it.get("asset") else "(无图)"
        print(f"  [{i + 1}] {it['title'][:30]} -> {asset_name}")

    print(f"\n目标实例: {connector.current_id}")
    if args.send:
        print("模式: 自动发送/生成")
    else:
        print("模式: 仅填入(不发送) — 请在豆啦啦中自己点击【生成】")

    if args.dry_run:
        return 0

    def on_log(msg):
        print(f"[INFO] {msg}")

    def on_progress(cur, total, title, status):
        print(f"[{cur}/{total}] {title[:30]} -> {status}")

    results = push_items(
        connector, items, auto_send=args.send, delay=args.delay,
        wait_manual=args.wait_manual, on_log=on_log, on_progress=on_progress)

    ok = sum(1 for r in results if r["ok"])
    print(f"\n完成: {ok}/{len(results)} 成功")
    failed = [r for r in results if not r["ok"]]
    if failed:
        print("失败项:")
        for r in failed:
            print(f"  {r['title']}: {r.get('error')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
