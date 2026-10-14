#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""豆啦啦(Dola)连接器包。

这是与豆啦啦无印浏览器通信的 稳定契约层。
上层功能模块（如 prompt_pusher）只通过 DolaConnector 与豆啦啦交互，
不应自行拼豆啦啦的 API URL。

用法:
    from dola_connector import DolaConnector
    conn = DolaConnector()              # 默认 http://127.0.0.1:17823
    instances = conn.list_instances()   # 列出全部实例
    conn.ensure_instance("Dola-32")     # 切到 Dola-32
    conn.paste_text("你好")             # 填文本到当前实例
    conn.paste_images(["c:/a.png"])     # 附图
    conn.send()                         # 发送/生成(一般不自动调)
"""
from .client import DolaConnector, Instance

__all__ = ["DolaConnector", "Instance"]
__version__ = "1.0.0"
