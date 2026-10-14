#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_manager 后端：标准库 http.server，提供 REST API + 托管前端静态文件。

仅通过 dola_connector 与豆啦啦通信。无第三方依赖，只用 Python 标准库。
"""
from __future__ import annotations

import os
import sys
import json
import re
import string
import time
import urllib.parse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 让 dola_connector 可被导入（prompt_manager 与 dola_connector 同为豆啦啦辅助/ 下的兄弟包）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dola_connector import DolaConnector  # noqa: E402

from .parser import parse_shots, read_text_file, norm_stem  # noqa: E402
from .matchers import prepare_match, build_shot_mapping  # noqa: E402

WEB_DIR = os.path.join(_HERE, "web")
STATE_DIR = os.path.join(_HERE, "state")
ADDED_FILE = os.path.join(STATE_DIR, "added_items.json")
ASSETS_FILE = os.path.join(STATE_DIR, "assets.json")

os.makedirs(STATE_DIR, exist_ok=True)

DEFAULT_PORT = 8899
# 版本标记：每次修复匹配/推送逻辑后递增，方便用户确认是否跑到了新代码
SERVER_VERSION = "2026-10-14.edit-and-save"
_lock = threading.Lock()

# ---------------------------------------------------------------- 运行日志
# 把运行期异常（含完整堆栈）落盘，方便排障；控制台窗口关掉也不丢。
LOG_FILE = os.path.join(STATE_DIR, "server.log")


def _log(msg: str):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".text", ".srt", ".ass", ".ssa",
    ".json", ".xml", ".csv", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".py", ".js", ".ts", ".html", ".htm", ".sh", ".bat", ".ps1", ".sql",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif"}


# ---------------------------------------------------------------- 持久化
def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def get_added() -> list:
    return _load_json(ADDED_FILE, [])


def get_assets() -> list:  # list of paths
    return _load_json(ASSETS_FILE, [])


def _asset_lib() -> list:
    return [{"path": p, "name": os.path.basename(p), "stem": norm_stem(p)}
            for p in get_assets() if os.path.isfile(p)]


def _collect_images(item: str) -> list:
    """递归收集 item（单个图片文件或文件夹）下的所有图片路径。

    文件夹会深入所有子目录（按图片扩展名过滤），避免用户把素材按
    角色/场景分文件夹存放时顶层扫不到、导入后资产库为空的问题。
    """
    out = []
    if os.path.isfile(item):
        if os.path.splitext(item)[1].lower() in IMAGE_EXTS:
            out.append(item)
        return out
    if os.path.isdir(item):
        for root, _dirs, files in os.walk(item):
            for fn in sorted(files):
                if os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
                    fp = os.path.join(root, fn)
                    if os.path.isfile(fp):
                        out.append(fp)
        return out
    return out


def match_file_for(prompt_path: str) -> str:
    return prompt_path + ".match.json"


# ---------------------------------------------------------------- 工具
def _list_dir(path: str):
    """列目录子项，目录在前、文件在后；文本/图片文件按扩展名过滤。"""
    if not os.path.isdir(path):
        return None
    items = []
    try:
        entries = sorted(os.listdir(path))
    except Exception:
        return []
    dirs, files = [], []
    for name in entries:
        full = os.path.join(path, name)
        if os.path.isdir(full):
            dirs.append({"name": name, "path": full, "type": "dir"})
        elif os.path.isfile(full):
            ext = os.path.splitext(name)[1].lower()
            if ext in TEXT_EXTS or ext in IMAGE_EXTS:
                files.append({"name": name, "path": full, "type": "file",
                              "kind": "image" if ext in IMAGE_EXTS else "text",
                              "ext": ext})
    return dirs + files


def _drives():
    """列出本机可用盘符 + 常用用户文件夹，供可视化选择器使用。"""
    drives = []
    for d in string.ascii_uppercase:
        root = f"{d}:\\"
        if os.path.exists(root):
            drives.append({"name": f"{d}:\\", "path": root, "type": "drive"})
    # 常用用户目录快捷入口
    extras = []
    for label, env in (("桌面", "USERPROFILE"), ("文档", "USERPROFILE"),
                       ("下载", "USERPROFILE"), ("图片", "USERPROFILE")):
        base = os.environ.get(env, "")
        if not base:
            continue
        sub = {
            "桌面": "Desktop", "文档": "Documents",
            "下载": "Downloads", "图片": "Pictures",
        }.get(label)
        p = os.path.join(base, sub) if sub else base
        if os.path.isdir(p) and not any(e["path"] == p for e in extras):
            extras.append({"name": label, "path": p, "type": "folder"})
    return drives + extras


# ---------------------------------------------------------------- 连接豆啦啦
_CONNECTOR = DolaConnector()
_connector_lock = threading.Lock()


def _instances():
    try:
        with _connector_lock:
            return [i.__dict__ for i in _CONNECTOR.list_instances()]
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- 请求处理
class Handler(BaseHTTPRequestHandler):
    server_version = "PromptManager/1.0"

    # 安静日志
    def log_message(self, *args):
        pass

    def handle_error(self, request, client_address):
        # 把请求级异常记到日志，避免只在控制台一闪而过
        import traceback as _tb
        try:
            _log("请求处理异常 (来自 %s):\n%s" % (client_address, _tb.format_exc()))
        except Exception:
            pass
        super().handle_error(request, client_address)

    def _send(self, code, obj=None, ctype="application/json; charset=utf-8"):
        body = b""
        if obj is not None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return {}

    def _serve_static(self, rel):
        if rel in ("", "/"):
            rel = "/index.html"
        fpath = os.path.normpath(os.path.join(WEB_DIR, rel.lstrip("/")))
        if not fpath.startswith(WEB_DIR) or not os.path.isfile(fpath):
            self._send(404, {"error": "not found"})
            return
        ctype = "text/html; charset=utf-8"
        if fpath.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif fpath.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        with open(fpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/version":
            self._send(200, {"version": SERVER_VERSION})
            return

        if path == "/api/shutdown":
            # 受控退出：旧服务收到后自行终止，避免外部 taskkill 误杀系统进程
            self._send(200, {"ok": True})
            try:
                self.wfile.flush()
            except Exception:
                pass
            os._exit(0)
            return

        if path == "/" or path.startswith("/web/") or path in ("/index.html", "/app.js", "/style.css"):
            self._serve_static(path)
            return

        if path == "/api/roots":
            self._send(200, {"roots": get_added()})
            return

        if path == "/api/drives":
            self._send(200, {"drives": _drives()})
            return

        if path == "/api/list":
            p = qs.get("path", [""])[0]
            res = _list_dir(p)
            if res is None:
                self._send(400, {"error": "目录不存在"})
            else:
                self._send(200, {"path": p, "children": res})
            return

        if path == "/api/instances":
            self._send(200, {"instances": _instances()})
            return

        if path == "/api/assets":
            self._send(200, {"assets": _asset_lib()})
            return

        if path == "/api/asset":
            p = qs.get("path", [""])[0]
            if p and os.path.isfile(p):
                ext = os.path.splitext(p)[1].lower()
                ctype = {
                    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
                }.get(ext, "application/octet-stream")
                with open(p, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            self._send(404, {"error": "not found"})
            return

        if path == "/api/file":
            p = qs.get("path", [""])[0]
            if not p or not os.path.isfile(p):
                self._send(400, {"error": "文件不存在"})
                return
            try:
                text, enc = read_text_file(p)
            except Exception as e:
                self._send(400, {"error": f"读取失败：{e}"})
                return
            shots = parse_shots(text)
            lib = _asset_lib()
            prep = prepare_match(shots, lib, text)
            # 已保存的匹配（新格式：资产名 -> 图；旧格式 mapping 兼容忽略）
            saved = _load_json(match_file_for(p), {})
            name_to_image = saved.get("name_to_image")
            if not isinstance(name_to_image, dict):
                name_to_image = prep["name_to_image"]
            # 展开为每个分镜的完整图片列表
            mapping = build_shot_mapping(prep["shot_refs"], name_to_image)
            for s in shots:
                s["asset_paths"] = mapping.get(s["index"], [])
            self._send(200, {
                "path": p,
                "name": os.path.basename(p),
                "encoding": enc,
                "shots": shots,
                "asset_names": prep["asset_names"],
                "name_to_image": name_to_image,
                "shot_refs": prep["shot_refs"],
                "library": lib,
            })
            return

        self._send(404, {"error": "unknown endpoint"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body()

        if path == "/api/roots":
            # 新增根节点 {path, type:'folder'|'file'}
            p = body.get("path", "")
            typ = body.get("type", "folder")
            if not p or not os.path.exists(p):
                self._send(400, {"error": "路径不存在"})
                return
            if typ == "folder" and not os.path.isdir(p):
                self._send(400, {"error": "不是文件夹"})
                return
            if typ == "file" and not os.path.isfile(p):
                self._send(400, {"error": "不是文件"})
                return
            roots = get_added()
            if not any(r["path"] == p for r in roots):
                roots.append({"path": p, "type": typ})
                _save_json(ADDED_FILE, roots)
            self._send(200, {"roots": roots})
            return

        if path == "/api/roots/remove":
            p = body.get("path", "")
            roots = [r for r in get_added() if r["path"] != p]
            _save_json(ADDED_FILE, roots)
            self._send(200, {"roots": roots})
            return

        if path == "/api/assets":
            # {paths:[...]} 追加资产（支持图片文件或图片所在文件夹；文件夹递归扫描）
            new = body.get("paths", []) or []
            added = get_assets()
            imported = 0
            for item in new:
                for fp in _collect_images(item):
                    if fp not in added:
                        added.append(fp)
                        imported += 1
            _save_json(ASSETS_FILE, added)
            self._send(200, {"assets": _asset_lib(), "imported": imported})
            return

        if path == "/api/assets/remove":
            p = body.get("path", "")
            added = [a for a in get_assets() if a != p]
            _save_json(ASSETS_FILE, added)
            self._send(200, {"assets": _asset_lib()})
            return

        if path == "/api/match":
            # {path, name_to_image:{资产名: 图片path|""}} 保存资产名->图 映射
            p = body.get("path", "")
            name_to_image = body.get("name_to_image", {})
            name_to_image = {k: (v or None) for k, v in name_to_image.items()}
            # 重新解析以拿到分镜引用，展开为每分镜图片列表后回传
            mapping = {}
            try:
                if p and os.path.isfile(p):
                    text, _ = read_text_file(p)
                    shots = parse_shots(text)
                    prep = prepare_match(shots, _asset_lib(), text)
                    mapping = build_shot_mapping(prep["shot_refs"], name_to_image)
            except Exception:
                mapping = {}
            _save_json(match_file_for(p), {"name_to_image": name_to_image})
            self._send(200, {"ok": True, "mapping": mapping})
            return

        if path == "/api/file/save":
            # {path, index, text} 把某个分镜的新文本原位写回文件。
            # 只覆盖该分镜自身的字符区间 [start, end)，文件其余部分原样保留；
            # 首次保存前自动生成 <文件>.bak 原件备份（已存在则不覆盖）。
            p = body.get("path", "")
            idx = body.get("index", None)
            new_text = body.get("text", "")
            if not p or not os.path.isfile(p):
                self._send(400, {"error": "文件不存在"})
                return
            if not isinstance(new_text, str) or not new_text.strip():
                self._send(400, {"error": "保存内容不能为空"})
                return
            try:
                idx = int(idx)
            except Exception:
                self._send(400, {"error": "分镜序号无效"})
                return
            try:
                raw_text, _enc = read_text_file(p)
                norm = raw_text.replace('\r\n', '\n').replace('\r', '\n')
                shots = parse_shots(norm)
                target = next((s for s in shots if s.get("index") == idx), None)
                if target is None:
                    self._send(400, {"error": f"找不到分镜 #{idx}（文件可能已变化，请重新打开）"})
                    return
                start, end = target.get("start"), target.get("end")
                if not isinstance(start, int) or not isinstance(end, int) \
                        or not (0 <= start <= end <= len(norm)):
                    self._send(400, {"error": "分镜定位失败，请重新打开文件"})
                    return
                content = norm[:start] + new_text.rstrip('\n') + norm[end:]
                # 首次保存前备份原件（保留最初版本，重复保存不覆盖备份）
                bak = p + ".bak"
                if not os.path.exists(bak):
                    try:
                        with open(p, "rb") as f:
                            _bak = f.read()
                        with open(bak, "wb") as f:
                            f.write(_bak)
                    except Exception:
                        pass  # 备份失败不阻止保存
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
                _log(f"保存分镜 #{idx} -> {p}（{len(content)} 字符）")
                self._send(200, {"ok": True, "index": idx, "chars": len(content)})
            except Exception as e:
                self._send(500, {"error": f"保存失败：{e}"})
            return

        if path == "/api/push":
            # {instance, text, assets:[paths], send:false}
            instance = body.get("instance", "")
            text = body.get("text", "")
            assets = body.get("assets", []) or []
            do_send = bool(body.get("send", False))
            if not text and not assets:
                self._send(400, {"error": "文本与资产不能同时为空"})
                return
            try:
                with _connector_lock:
                    _CONNECTOR.ensure_instance(instance)
                    if text:
                        _CONNECTOR.paste_text(text)
                    if assets:
                        _CONNECTOR.paste_images(assets)
                    if do_send:
                        _CONNECTOR.send()
                self._send(200, {"ok": True, "sent": do_send})
            except Exception as e:
                err = str(e)
                # Dola 常见可操作建议：输入框未聚焦
                if "文字未出现在输入框" in err or "请点击豆包输入框" in err:
                    err = ("豆啦啦未能把文字填入输入框（窗口可能未在前台或输入框未聚焦）。"
                           "请先切到豆啦啦窗口、点一下聊天输入框，再点推送。")
                self._send(500, {"ok": False, "error": err, "raw": str(e)})
            return

        self._send(404, {"error": "unknown endpoint"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        if path == "/api/roots":
            p = qs.get("path", [""])[0]
            roots = [r for r in get_added() if r["path"] != p]
            _save_json(ADDED_FILE, roots)
            self._send(200, {"roots": roots})
            return
        if path == "/api/assets":
            p = qs.get("path", [""])[0]
            if not p:
                # 清空全部已选资产
                _save_json(ASSETS_FILE, [])
                self._send(200, {"assets": []})
                return
            added = [a for a in get_assets() if a != p]
            _save_json(ASSETS_FILE, added)
            self._send(200, {"assets": _asset_lib()})
            return
        self._send(404, {"error": "unknown endpoint"})


def main():
    import sys as _sys
    import traceback as _tb
    port = DEFAULT_PORT
    print(f"[prompt_manager] 版本={SERVER_VERSION}")
    print(f"[prompt_manager] 准备启动，Python={_sys.version.split()[0]}，端口={port}")
    server = None
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"[prompt_manager] 启动失败：无法绑定 127.0.0.1:{port} —— {e}")
        print(f"[prompt_manager] 很可能 8899 已被其他进程占用。请先关闭旧窗口/结束占用进程，再重新双击启动器。")
        raise
    print(f"[prompt_manager] 服务已启动: http://127.0.0.1:{port}/")
    print(f"[prompt_manager] 静态目录: {WEB_DIR}")
    print(f"[prompt_manager] 异常日志: {LOG_FILE}")

    # 自愈循环：任何未预期的异常都记录并立刻重启服务，
    # 单个请求出错绝不会让整个服务退出（避免“第二次推送就失败”）。
    while True:
        try:
            server.serve_forever()
            # serve_forever 正常返回（通常是被 shutdown 调用），视为退出
            break
        except KeyboardInterrupt:
            print("[prompt_manager] 收到 Ctrl+C，正在关闭…")
            break
        except Exception as e:
            _log("serve_forever 崩溃，3 秒后自动重启：%s\n%s" % (e, _tb.format_exc()))
            print(f"[prompt_manager] 服务异常，正在自动重启：{e}")
            try:
                server.server_close()
            except Exception:
                pass
            time.sleep(3)
            # 重新创建 server（端口可能短暂未释放）
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            except OSError:
                time.sleep(2)
    try:
        if server:
            server.server_close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
