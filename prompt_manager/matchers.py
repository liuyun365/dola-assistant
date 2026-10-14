#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产匹配：以「资产名 -> 图片」为中心。

设计目标（用户需求）：
  - 资产匹配是「资产的对应」：左边列出资产名（如 沈清辞），右边下拉选择其图片。
  - 预先做模糊匹配（文件名相似度），用户可手动改。
  - 提交后，每个分镜按自身引用的资产名展开为「完整」的图片集。
  - 同一个资产名若在多个分镜出现，匹配界面只出现一次，但每个分镜都拿到完整图片。

资产名来源（唯一）：
  提示词里的「图N」标记（图一：沈清辞 / 图1: 街道 / 图二为客厅）——按图序排序，图片顺序即资产顺序。
  说明：正文出现的人名/场景/物品、以及 资产：/参考图： 这类标签，都不再提取，留给 AI 自行生成；
        只有明确以「图N」开头的行才纳入资产参考。
"""
from __future__ import annotations
import difflib
import os
import re
from typing import Any, Dict, List, Optional

from .parser import extract_shot_assets_ordered, extract_shot_assets_full, norm_stem


def _path_keys(path: str) -> List[str]:
    """用于匹配的候选键：文件名(去扩展名) + 各级父目录名；'_' '-' 再拆开。

    关键改进：即使图片本身叫 '正面.png'，只要它放在 '角色/沈清辞/' 文件夹下，
    也能靠父目录名 '沈清辞' 命中资产名 '沈清辞'（解决"人物图片按角色分文件夹后匹配不上"）。
    """
    parts = path.replace('\\', '/').split('/')
    keys: List[str] = []
    for part in parts:
        if not part:
            continue
        stem, _ = os.path.splitext(part)
        k = stem.strip().lower()
        if k:
            keys.append(k)
        # '沈清辞_正面' -> ['沈清辞', '正面'] 也作为候选键
        for sub in re.split(r'[_\-]', k):
            sub = sub.strip()
            if sub:
                keys.append(sub)
    return keys


def fuzzy_image_for_name(name: str, asset_lib: List[Dict[str, str]]) -> Optional[str]:
    """给一个资产名，从资产库里模糊挑一张最像的图。返回 path 或 None。"""
    name_l = (name or '').strip().lower()
    if not name_l or not asset_lib:
        return None

    # 1) 精确 / 包含关系：资产名 == 某候选键（文件名或父目录名），或相互包含
    cands = []
    for a in asset_lib:
        for k in _path_keys(a['path']):
            if not k:
                continue
            if name_l == k:
                cands.append((1.0, a['path']))
            elif name_l in k or k in name_l:
                # 重叠占比越高越优先；长度接近的优先
                score = len(name_l) / max(len(k), 1)
                cands.append((score, a['path']))
    if cands:
        cands.sort(reverse=True, key=lambda x: x[0])
        return cands[0][1]

    # 2) difflib 兜底：文件名里找最接近的资产名
    stems = [norm_stem(a['path']) for a in asset_lib]
    best = difflib.get_close_matches(name_l, stems, n=1, cutoff=0.5)
    if best:
        for a in asset_lib:
            if norm_stem(a['path']) == best[0]:
                return a['path']
    return None


def locate_image_by_path(path_fragment: str, asset_lib: List[Dict[str, str]]) -> Optional[str]:
    """文中直接给出了图片路径（如 人物设定/女主_小三形象_v1.png），在资产库里按文件名定位。

    先精确 basename 匹配，再按文件名 stem 包含关系兜底（忽略大小写与分隔符差异）。
    """
    if not path_fragment or not asset_lib:
        return None
    frag = path_fragment.replace('\\', '/')
    base = frag.split('/')[-1].lower()
    base_stem = os.path.splitext(base)[0]
    # 1) 精确 basename
    for a in asset_lib:
        if a['path'].replace('\\', '/').lower().endswith('/' + base) or \
           a['path'].replace('\\', '/').lower().endswith(base):
            return a['path']
    # 2) stem 包含 / 被包含
    if base_stem:
        for a in asset_lib:
            s = norm_stem(a['path'])
            if base_stem in s or s in base_stem:
                return a['path']
    return None



def _shot_ordered_full(shot: Dict[str, Any]) -> List:
    """一个分镜内、按图序的 (seq, name, path) 列表。"""
    return extract_shot_assets_full(shot.get('text', '') or '')


def _category_words(asset_lib: List[Dict[str, str]]) -> List[str]:
    """从资产库文件名推断「类别词」（如 女主 / 丈夫 / 婆婆 / 高档餐厅 / 钻石项链）。

    取文件名第一个 '_' 之前的部分；长词优先，避免 '女主' 抢先于 '女主旧眼镜'。
    """
    seen = set()
    cats: List[str] = []
    for a in asset_lib:
        cat = norm_stem(a['path']).split('_')[0]
        if cat and cat not in seen:
            seen.add(cat)
            cats.append(cat)
    cats.sort(key=len, reverse=True)
    return cats


def _fallback_from_text(text: str, asset_lib: List[Dict[str, str]]) -> List[str]:
    """兜底：一段内没有「图N」写法时（如分镜站位文件），扫描文中出现的角色/场景词。"""
    if not text or not asset_lib:
        return []
    cats = _category_words(asset_lib)
    found: List[str] = []
    seen = set()
    for c in cats:
        if c and c in text and c not in seen:
            seen.add(c)
            found.append(c)
    return found


def _shot_ordered_names(shot: Dict[str, Any]) -> List[str]:
    """一个分镜内、按图序去重后的资产名列表。"""
    seen = set()
    out: List[str] = []
    for (_seq, name, _p) in _shot_ordered_full(shot):
        n = (name or '').strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def collect_asset_names(shots: List[Dict[str, Any]], asset_lib: List[Dict[str, str]],
                        full_text: str) -> List[str]:
    """收集文档里出现过的去重资产名（文档顺序、首次出现优先）。

    仅来自分镜里的「图N」标记，不扫描正文、也不扫资产库文件名。
    """
    names: List[str] = []
    seen = set()
    for shot in shots:
        for n in _shot_ordered_names(shot):
            if n not in seen:
                seen.add(n)
                names.append(n)
    return names


def prepare_match(shots: List[Dict[str, Any]], asset_lib: List[Dict[str, str]],
                  full_text: str) -> Dict[str, Any]:
    """为匹配界面准备数据。

    返回：
      asset_names  : 去重后的资产名列表（文档顺序）
      name_to_image: {资产名: 预匹配的图片 path 或 null}
      shot_refs    : {分镜index: [该分镜按图序引用的资产名]}
      library      : 资产库（供下拉）
    """
    # 每个分镜的有序资产（图序优先，含文中直接给出的路径）。
    # 兜底策略：仅当**整篇**都没有「图N」写法（如分镜站位文件）时，才用角色/场景关键词兜底；
    # 否则（标准提示词等已有图N参考对应）只走精确路径，避免混入「女主/丈夫」这类泛名污染匹配区。
    any_ref = any(_shot_ordered_full(s) for s in shots)
    shot_full: Dict[int, List] = {s['index']: _shot_ordered_full(s) for s in shots}
    if not any_ref:
        # 整篇都没有「图N」写法（如分镜站位文件），用角色/场景关键词兜底
        for s in shots:
            if not shot_full[s['index']]:
                fb = _fallback_from_text(s.get('text', '') or '', asset_lib)
                shot_full[s['index']] = [(900 + i, n, None) for i, n in enumerate(fb)]
    shot_ordered: Dict[int, List[str]] = {
        idx: [n for (_s, n, _p) in items] for idx, items in shot_full.items()
    }

    # 全局资产名（文档顺序，首次出现优先；仅来自「图N」标记）
    names: List[str] = []
    seen = set()
    for s in shots:
        for n in shot_ordered[s['index']]:
            if n not in seen:
                seen.add(n)
                names.append(n)

    # 第一遍：文中「图N对应路径」直接给出的，优先按路径在资产库精确定位
    name_to_image: Dict[str, Optional[str]] = {}
    for s in shots:
        for (_seq, n, p) in shot_full[s['index']]:
            if n and p and n not in name_to_image:
                loc = locate_image_by_path(p, asset_lib)
                if loc:
                    name_to_image[n] = loc

    # 第二遍：未定位到的，再用资产名做模糊匹配兜底
    for n in names:
        if n not in name_to_image or not name_to_image[n]:
            name_to_image[n] = fuzzy_image_for_name(n, asset_lib)

    shot_refs: Dict[int, List[str]] = {
        idx: [n for n in ordered if n in seen] for idx, ordered in shot_ordered.items()
    }

    return {
        "asset_names": names,
        "name_to_image": name_to_image,
        "shot_refs": shot_refs,
        "library": asset_lib,
    }


def build_shot_mapping(shot_refs: Dict[int, List[str]],
                       name_to_image: Dict[str, Optional[str]]) -> Dict[int, List[str]]:
    """根据 资产名->图 的映射，展开为每个分镜的完整图片列表。

    只保留有图的资产；同一资产不会在一个分镜里重复。
    """
    mapping: Dict[int, List[str]] = {}
    for idx, names in shot_refs.items():
        imgs: List[str] = []
        for n in names:
            img = name_to_image.get(n)
            if img and img not in imgs:
                imgs.append(img)
        mapping[idx] = imgs
    return mapping


# 兼容旧接口（保留，避免其它模块报错）
def auto_match(shots, asset_lib):
    prep = prepare_match(shots, asset_lib, '\n'.join(s.get('text', '') for s in shots))
    return build_shot_mapping(prep['shot_refs'], prep['name_to_image'])


def merge_match(shots, auto, manual):
    out = {}
    for shot in shots:
        idx = shot['index']
        out[idx] = manual.get(idx, auto.get(idx, []))
    return out
