#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""豆啦啦(Dola)连接器：与豆啦啦本地自动化 API 通信的底层模块.

职责边界（稳定契约，后续功能模块只调用它，不在此改业务）:
- 实例管理：列出实例、查询当前、切换到指定实例
- 内容写入：把文本/图片填入当前实例的聊天输入框
- 触发动作：发送/生成、查询任务状态

不包含任何"提示词解析""资产匹配""批量编排"等业务逻辑——
那些属于上层功能模块（如 prompt_pusher）。

如需对接豆啦啦的新能力（新端点），在此增加对应方法即可；
功能模块只消费本类暴露的接口，不自己拼 URL。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .config import (
    DEFAULT_API_URL, DEFAULT_TIMEOUT,
    EP_HEALTH, EP_INSTANCE_ENSURE, EP_PASTE_TEXT, EP_PASTE_IMAGES,
    EP_SEND, EP_TASK_STATUS,
)


@dataclass
class Instance:
    """一个豆啦啦账号实例."""
    id: str
    name: str = ""
    platform: str = ""
    running: bool = False
    current: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Instance":
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "") or ""),
            platform=str(d.get("platform", "") or ""),
            running=bool(d.get("running", False)),
            current=bool(d.get("current", False)),
        )

    def __str__(self) -> str:
        state = "运行中" if self.running else "未运行"
        mark = " <== 当前" if self.current else ""
        return (f"{self.id}  名称={self.name}  平台={self.platform}  "
                f"{state}{mark}")


class DolaConnector:
    """豆啦啦本地自动化 API 的封装连接器（稳定契约）."""

    def __init__(self, api_url: str = DEFAULT_API_URL, timeout: int = DEFAULT_TIMEOUT):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._netloc = urllib.parse.urlparse(self.api_url).netloc or "127.0.0.1:17823"
        self._instances: List[Instance] = []
        self.current_id: Optional[str] = None

    # ---- 底层 HTTP ----
    def _call(self, method: str, path: str, body: Any = None, params: Optional[Dict] = None):
        url = self.api_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json", "Host": self._netloc},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                return e.code, {"ok": False, "message": str(e)}
        except Exception as e:
            raise RuntimeError(
                f"无法连接豆啦啦本地 API ({self.api_url})，"
                f"请确认豆啦啦无印浏览器已运行：{e}"
            )

    # ---- 实例管理 ----
    def health(self) -> Dict[str, Any]:
        """健康检查，返回完整 health 响应（含版本与实例列表）。"""
        s, j = self._call("GET", EP_HEALTH)
        if not j.get("ok"):
            raise RuntimeError(f"health 接口失败: {j}")
        return j

    def list_instances(self) -> List[Instance]:
        """列出所有实例，并缓存到 self._instances。"""
        j = self.health()
        self._instances = [Instance.from_dict(i) for i in j.get("instances", [])]
        return self._instances

    def get_current(self) -> Optional[Instance]:
        """返回当前实例（current=True），无则 None。"""
        for it in (self._instances or self.list_instances()):
            if it.current:
                return it
        return None

    def ensure_instance(self, which: Union[int, str]) -> Instance:
        """切换/确保某实例为"当前"。which: 序号(1-based) 或 id/名称(模糊匹配)。"""
        insts = self._instances or self.list_instances()
        if not insts:
            raise RuntimeError("没有可用的实例，请先在豆啦啦里打开至少一个账号实例。")
        target = self._resolve(which, insts)
        s, j = self._call("POST", EP_INSTANCE_ENSURE, {"instance_id": target.id})
        if not j.get("ok"):
            raise RuntimeError(f"切换实例失败: {j}")
        self.current_id = target.id
        return target

    @staticmethod
    def _resolve(which: Union[int, str], insts: List[Instance]) -> Instance:
        if isinstance(which, int):
            if 1 <= which <= len(insts):
                return insts[which - 1]
        else:
            w = str(which).lower()
            for it in insts:
                if w == it.id.lower() or w == it.name.lower():
                    return it
            for it in insts:
                if w in it.id.lower() or w in it.name.lower():
                    return it
        ids = ", ".join(i.id for i in insts)
        raise ValueError(f"未找到实例 '{which}'。可用: {ids}")

    def pick_default_instance(self) -> Instance:
        """无显式指定时: 优先当前实例, 否则第一个运行中的, 否则第一个。"""
        insts = self._instances or self.list_instances()
        cur = self.get_current()
        if cur:
            self.current_id = cur.id
            return cur
        for it in insts:
            if it.running:
                self.current_id = it.id
                return it
        if insts:
            self.current_id = insts[0].id
            return insts[0]
        raise RuntimeError("没有可用的实例。")

    # ---- 内容写入 ----
    def paste_text(self, text: str) -> Dict[str, Any]:
        """把文本填入当前实例的聊天输入框。"""
        s, j = self._call("POST", EP_PASTE_TEXT, {"text": text})
        if not j.get("ok"):
            msg = j.get("message", j)
            if "文字未出现在输入框" in str(msg) or "请点击豆包输入框" in str(msg):
                raise RuntimeError(
                    "豆啦啦未能把文字填入输入框（窗口可能未在前台或输入框未聚焦）。"
                    "请先切到豆啦啦窗口、点一下聊天输入框，再点推送。"
                )
            raise RuntimeError(f"填文本失败: {j}")
        return j

    def paste_images(self, paths: List[str]) -> Dict[str, Any]:
        """把本地图片路径贴入当前实例（豆啦啦会自行上传）。

        paths: 本地图片绝对路径列表；为空时直接返回成功、不发起请求。
        """
        paths = [p for p in (paths or []) if p]
        if not paths:
            return {"ok": True, "results": []}
        s, j = self._call("POST", EP_PASTE_IMAGES, {"paths": paths})
        if not j.get("ok"):
            raise RuntimeError(f"附图失败: {j}")
        return j

    # ---- 触发动作 ----
    def send(self) -> Dict[str, Any]:
        """触发发送/生成（默认业务流程不调用，由用户手动点）。"""
        s, j = self._call("POST", EP_SEND, {})
        return j

    def task_status(self, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """查询生成任务状态。"""
        params = {"instance_id": instance_id} if instance_id else {}
        s, j = self._call("GET", EP_TASK_STATUS, params=params)
        return j
