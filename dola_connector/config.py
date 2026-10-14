#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""豆啦啦(Dola)本地自动化 API —— 连接器的配置层.

本文件属于"连接器"的一部分，是稳定契约，后续不应随意改动。
豆啦啦无印浏览器内置 Automation 服务，默认监听 127.0.0.1:17823，
无需任何调试端口或 token，只要豆啦啦在运行即可调用。
"""
# 本地 API 地址（豆啦啦无印浏览器内置 Automation 服务）
DEFAULT_API_URL = "http://127.0.0.1:17823"
# 请求超时(秒)
DEFAULT_TIMEOUT = 15

# 端点
EP_HEALTH = "/api/health"                   # GET  列出所有实例 + 版本
EP_INSTANCE_ENSURE = "/api/instance/ensure"  # POST 切换/确保某实例为当前 (body: instance_id)
EP_PASTE_TEXT = "/api/paste/text"           # POST 把文本填入当前实例聊天框 (body: text)
EP_PASTE_IMAGES = "/api/paste/images"       # POST 把本地图片路径贴入当前实例 (body: paths[])
EP_SEND = "/api/send"                       # POST 触发发送/生成（默认不调用）
EP_TASK_STATUS = "/api/task/status"         # GET  查询生成任务 (param: instance_id)
