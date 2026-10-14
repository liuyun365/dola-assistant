#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词解析：把一份提示词文档切成「分镜(shot)」，并提取每段中的资产引用。

只做纯文本解析，不负责任何与豆啦啦通信的事（那归 dola_connector）。
支持的分镜标题写法（任一命中即视为新分镜起点）：
  - Markdown 标题：  # 镜头一 / ## 场景2 / ### 第3镜 / ### 分镜01-01｜块内00–06s｜客厅
  - 中文镜头/分镜/场景：镜头三：雨夜 / 分镜5 / 场景 02
  - 第n镜/第n集/第n场
  - 数字序号：   1. 2) 3、
  - 分隔线：     ---  （单独成行，作为分镜边界）
无标题时整篇当作一个分镜。

【重要】时间轴子片段不算分镜边界（2026-10-14 修复）：
  Seedance 2.5 标准提示词里，「### 镜头1｜00–30s｜标题」才是顶层分镜；
  块内「**时间轴细分：**」下的「分镜01-01：…」「分镜02-05：…」（连字符编号 N-NN）
  是同一条 30s 成片内部的片段，禁止拆成多个分镜。
  但分镜站位文件用 Markdown 标题「### 分镜01-01｜…」作主结构，仍正常切分
  （排除规则只作用于纯文本行，不影响 # 开头的 Markdown 标题）。
"""
from __future__ import annotations
import os
import re
from typing import Any, Dict, List

# ---- 分镜标题识别 ----
# 顺序很重要：先精确后宽松，避免把正文数字误判为分镜
_SHOT_KEYWORD = re.compile(r'(镜头|分镜|场景|镜|shot|scene)', re.I)
_ORDINAL = r'[0-9一二三四五六七八九十百千零]+[A-Za-z]?'

_HEADER_RES = [
    # 第N镜 / 第N集 / 第N场（N 可为阿拉伯或中文数字）
    re.compile(r'^第\s*([0-9一二三四五六七八九十百千零]+)\s*(镜|集|场|幕)\b\s*[:：]?\s*(.*)$'),
    # 镜头/分镜/场景/场/镜 + 序号 + 可选冒号标题
    re.compile(r'^(镜头|分镜|场景|场|镜|shot|scene)\s*[_#\-]?\s*'
               r'([0-9一二三四五六七八九十百千零]+[A-Za-z]?)\s*[:：]?\s*(.*)$', re.I),
    # 数字序号 1. 2) 3、
    re.compile(r'^\s*([0-9]{1,3})[.、)）]\s+(.+)$'),
    # 分隔线 --- （单独成行，作为分镜边界）
    re.compile(r'^\s*-{3,}\s*$'),
]

# Markdown 标题：仅当标题文本本身像「分镜」时才切分（避免 # 第一集 分镜 这类文档标题被误切）
_MD_HEAD_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')
_MD_HEAD_SHOT = re.compile(
    r'(镜头|分镜|场景|镜|shot|scene)\s*[_#\-]?\s*' + _ORDINAL
    + r'|第\s*[0-9一二三四五六七八九十百千零]+\s*(镜|集|场|幕)', re.I)


_SEP_RE = re.compile(r'^\s*-{3,}\s*$')          # 分隔线 ---

# 时间轴子片段标记：纯文本行「分镜01-01：…」「镜头2-3 …」（连字符编号 N-NN）。
# 这是 30s 镜头块内部的片段，不是分镜边界；仅匹配行首（# 开头的 Markdown 标题不受影响）。
_SUBSHOT_RE = re.compile(
    r'^(?:镜头|分镜|场景|场|镜|shot|scene)\s*'
    r'[0-9一二三四五六七八九十百千零两]+\s*[-–—]\s*[0-9一二三四五六七八九十百千零两]+',
    re.I,
)


def _match_header(line: str):
    """若 line 是分镜标题行，返回该行原文（作为分镜标题），否则 None。"""
    s = line.strip()
    if not s:
        return None
    # 时间轴子片段（分镜01-01：…）优先排除：它不是顶层分镜边界
    if _SUBSHOT_RE.match(s):
        return None
    for r in _HEADER_RES:
        if r.match(s):
            return s
    # Markdown 标题：标题文本需显含「分镜」信号才切分
    m = _MD_HEAD_RE.match(s)
    if m and _MD_HEAD_SHOT.search(m.group(2)):
        return s
    return None



# 真实分镜内容标记：含这些词的段落才是可推送的「分镜」，否则视为总览/标题段
_SHOT_CONTENT_RE = re.compile(
    r'(参考对应|角色映射|场景映射|物品映射|声线参考|生成规格|初始站位|'
    r'时间轴|分镜|硬切|机位|同期声音|画风|镜头|场景|人物设定|场景设定|道具设定)'
)

# 文档级总览标记：章节「拆分结果」说明、源文件、时长汇总、镜头块规划清单等。
# 这些是章节导览/规划信息，不是可推送的分镜正文。注意总览里也常含「镜头」二字
# （如 "- 镜头1｜00-30s｜…"），所以要用这套「强总览标记」优先判定，避免被
# _SHOT_CONTENT_RE 误当成真实分镜内容。
_OVERVIEW_MARK_RE = re.compile(
    r'(拆分结果|源文件\s*[:：]|\d\.\d\s*原时长|'
    r'按\s*\d\.\d[^\n]{0,30}规则拆分|共约\s*\d+\s*秒|'
    r'拆分为\s*\d+\s*[个名]?\s*[""“]?镜头)'
)


def _is_overview_shot(title: str, body: str) -> bool:
    """判断一个分镜桶是否为「文档总览/标题段」（应被过滤掉，不推送）。

    特征：标题为空、或标题是 Markdown 标题，且属于以下任一情况：
      1) 命中「文档级总览标记」（拆分结果/源文件/原时长/按X.X规则拆分/共约N秒/
         拆分为N个镜头块）——典型如「# 第002章｜第一刀｜Seedance 2.5 30秒分镜提示词」
         +「## 拆分结果」+「- 镜头1｜…」~「- 镜头7｜…」这种章节规划总览；
      2) 正文中不含任何真实分镜内容标记（参考对应/分镜/机位/同期声音…）。
    典型即文档首行的「# 《剧名》第00X集｜…标准提示词」+「全文使用seedance2.5生成」，
    以及上述「拆分结果」总览段，被误切成「分镜」时，都应直接剔除。
    """
    t = (title or '').strip()
    b = (body or '').strip()
    title_like = (not t) or re.match(r'^#{1,6}\s', t)
    if not title_like:
        return False
    combined = t + '\n' + b
    # 文档级总览标记优先：总览里也含「镜头」二字，但不能因此当成真实分镜内容
    if _OVERVIEW_MARK_RE.search(combined):
        return True
    if _SHOT_CONTENT_RE.search(combined):
        return False
    return True


def parse_shots(text: str) -> List[Dict[str, Any]]:
    """把文本切成分镜列表。每个元素:
        {index, title, body, text, start, end, asset_paths}
      - title: 该分镜标题行（可能为空）
      - body : 标题下的正文
      - text : title + body 拼接的完整可复制文本
      - start/end: 该分镜在**规范化文本**中的字符区间 [start, end)
        （供保存时原位替换：只覆盖该分镜自身文字，不动文件其它部分）
    """
    norm = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = norm.split('\n')
    # 每行在 norm 中的起始偏移
    offsets: List[int] = []
    _pos = 0
    for ln in lines:
        offsets.append(_pos)
        _pos += len(ln) + 1  # +1 为行尾 '\n'

    def _new_bucket(title=None, start=None):
        return {'title': title, 'lines': [], 'start': start, 'end': None}

    buckets: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = _new_bucket()

    def _has_content(b):
        return b['title'] is not None or ''.join(b['lines']).strip()

    for i, line in enumerate(lines):
        if _SEP_RE.match(line):
            # 分隔线：若当前段已有内容则切分；否则忽略
            if _has_content(cur):
                buckets.append(cur)
                cur = _new_bucket()
            continue
        h = _match_header(line)
        if h is not None:
            if _has_content(cur):
                buckets.append(cur)
            cur = _new_bucket(title=h, start=offsets[i])
            cur['end'] = offsets[i] + len(line)
            continue
        if cur['start'] is None:
            cur['start'] = offsets[i]
        cur['lines'].append(line)
        cur['end'] = offsets[i] + len(line)

    # 收尾
    if _has_content(cur):
        buckets.append(cur)

    # 丢弃「仅有标题、无正文」的桶（文档级标题、总览里的镜头清单项等）。
    # 这些没有可推送内容；若把无正文标题并入下一桶标题，反而会污染真正分镜标题
    # （典型：把总览最后一条「镜头14｜用股权」缀到真正「镜头1」标题前），故直接丢弃。
    buckets = [b for b in buckets if ''.join(b['lines']).strip()]

    shots: List[Dict[str, Any]] = []
    for i, b in enumerate(buckets, 1):
        title = (b['title'] or '').strip()
        body = '\n'.join(b['lines']).strip('\n')
        full = (title + '\n' + body).strip('\n') if title else body
        shots.append({
            'index': i,
            'title': title,
            'body': body,
            'text': full,
            'start': b['start'] if b['start'] is not None else 0,
            'end': b['end'] if b['end'] is not None else len(norm),
            'asset_paths': [],   # 由匹配阶段填充
        })

    # 过滤「文档总览 / 标题段」：如首行文档标题「# 《剧名》第00X集…」，它不是可推送分镜
    shots = [s for s in shots if not _is_overview_shot(s['title'], s['body'])]

    # 重新连续编号（剔除后保持 1..N 连续）
    for i, s in enumerate(shots, 1):
        s['index'] = i

    if not shots:
        shots.append({'index': 1, 'title': '', 'body': text, 'text': text,
                      'start': 0, 'end': len(norm), 'asset_paths': []})
    return shots


# ---- 资产引用提取 ----
# 显式写法： 资产：客厅、街道   /  参考图: a.jpg, b.png   /  配图：人物1
_ASSET_TAG_RES = [
    re.compile(r'(?:资产|参考图|参考|配图|图)\s*[:：]\s*([^\n，。；;]+)'),
    re.compile(r'\[(?:资产|参考|图)[：:]?\s*([^\]\n，。；;]+)\]'),
]

_TOKEN_SPLIT = re.compile(r'[，,、；;|/\\]+\s*|\s+')


def extract_asset_refs(text: str) -> List[str]:
    """从一段文本中提取显式的资产引用名（如「资产：客厅,街道」→ ['客厅','街道']）。"""
    refs: List[str] = []
    for r in _ASSET_TAG_RES:
        for m in r.finditer(text or ''):
            chunk = m.group(1).strip()
            for tok in _TOKEN_SPLIT.split(chunk):
                tok = tok.strip().strip('[]()（）')
                if tok and len(tok) >= 1:
                    refs.append(tok)
    # 去重保序
    seen = set()
    out = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ---------------------------------------------------------------- 图N 序号资产名提取
# 用户提示词中常见的写法（资产名按图序排序，图片顺序即资产顺序）：
#   图一：沈清辞 / 图1: 街道 / 图二 为 客厅 / 图三 沈清辞转身
_CN_NUM = {
    '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}
_IMG_NUM_CLS = r'[0-9一二三四五六七八九十百千两]+'
_IMG_ASSET_RES = [
    # 图一：沈清辞 / 图1: 街道
    re.compile(r'图\s*(' + _IMG_NUM_CLS + r')\s*[:：]\s*([^，。；;：\s、|]+)'),
    # 图一为沈清辞 / 图2为客厅
    re.compile(r'图\s*(' + _IMG_NUM_CLS + r')\s*为\s*([^，。；;：\s、|]+)'),
    # 图一＝陈母 / 图1=街道（全角/半角等号，角色映射行常用写法）
    re.compile(r'图\s*(' + _IMG_NUM_CLS + r')\s*[＝=]\s*([^，。；;：\s、|＝=]+)'),
    # 图五是客厅（"是"字写法，场景映射常用）
    re.compile(r'图\s*(' + _IMG_NUM_CLS + r')\s*是\s*([^，。；;：\s、|＝=]+)'),
    # 图一 沈清辞（空格分隔，名称紧接）
    re.compile(r'图\s*(' + _IMG_NUM_CLS + r')\s+([一-龥A-Za-z0-9_]{1,12})'),
]

# 占位/无意义资产名：命中直接丢弃（如「图一：无独立参考图」）
_ASSET_NAME_BLACKLIST = {
    '无', '暂无', '无图', '无参考图', '无独立参考图', '无对应', '略',
    '无场景', '无物品', '谁', '什么', '哪', '未知', '待定',
}

# 场景/物品映射行：整行即资产名清单。
# 部分剧集「场景映射：客厅」「物品映射：婚纱、戒指」不带图N，也是显式资产声明
# （用户确认：资产 = 人物 + 场景 + 物品，物品可无）。seq 取 800/850 排在人物之后。
_MAP_LINE_RES = [
    (re.compile(r'场景映射\s*[:：]\s*([^\n]+)'), 800),
    (re.compile(r'物品映射\s*[:：]\s*([^\n]+)'), 850),
]
# 图N 形式的 token（图五为…/图三＝…）由图N规则负责，裸名解析跳过
_TOKEN_IS_IMGN_RE = re.compile(r'^图\s*[0-9一二三四五六七八九十百千两]')

# 「图N对应编号 路径.png」写法（如：图一对应F02 人物设定/女主_小三形象_v1.png）
# 剧中「参考对应」行直接内嵌了图片路径，资产名与图片都从路径解析，无需模糊匹配。
_IMG_REF_RES = re.compile(
    r'图\s*(' + _IMG_NUM_CLS + r')\s*对应\s*[A-Za-z0-9]*\s*'
    r'([^\s；;（）()]+\.(?:png|jpe?g|webp|gif|PNG|JPE?G|WEBP|GIF))',
    re.I,
)


def _cn_to_int(s: str):
    """把阿拉伯或中文数字（0-99）转成 int；无法识别返回 None。"""
    s = (s or '').strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return int(s)
        except Exception:
            return None
    total, cur, ok = 0, 0, False
    for ch in s:
        if ch == '十':
            ok = True
            total += (cur * 10) if cur else 10
            cur = 0
        elif ch in _CN_NUM:
            ok = True
            cur = _CN_NUM[ch]
        else:
            break
    total += cur
    return total if ok else None


# ---- 资产名清洗：去掉括号、身高/年龄/尺寸等冗余，只留名字 ----
_HEIGHT_RE = re.compile(r'身高\s*\d+(?:\.\d+)?\s*(?:cm|厘米|米|m)?', re.I)
_MEASURE_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:cm|厘米|米|m)', re.I)
_YEAR_RE = re.compile(r'\d{1,3}\s*岁')
_PAREN_RE = re.compile(r'[（(][^（）()]*[)）]')        # 成对括号 (...)
_PAREN_OPEN_RE = re.compile(r'[（(][^）)]*$')          # 未闭合左括号
# 结尾修饰词：女/男/正面/侧面/…（仅当修饰词前是名字才剥离）
_TRAIL_RE = re.compile(
    r'([一-龥A-Za-z0-9]{1,})(?:_?(?:女|男|正面|侧面|侧脸|正脸|全身|半身|'
    r'站姿|坐姿|背影|特写|远景|中景|近景|正面照|侧身))$'
)


def clean_asset_name(raw: str) -> str:
    """清洗「图N」后面的资产名，只留纯名字。

    例：
      '沈清辞（女，175cm）' -> '沈清辞'
      '沈清辞 175cm 正面'   -> '沈清辞'
      '沈清辞正面'          -> '沈清辞'
      '图一：沈清辞（女'    -> '沈清辞'   （未闭合括号也能处理）
    """
    s = (raw or '').strip()
    if not s:
        return ''
    s = _PAREN_RE.sub('', s)
    s = _PAREN_OPEN_RE.sub('', s)
    s = _HEIGHT_RE.sub('', s)
    s = _YEAR_RE.sub('', s)
    s = _MEASURE_RE.sub('', s)
    # 按分隔符切取第一段（逗号/句号/空格/顿号等）
    s = re.split(r'[\s，,。.；;：:、|/\\]+', s)[0]
    # 去掉结尾的修饰词（女/男/姿态/景别）——仅当修饰词前是名字
    s = _TRAIL_RE.sub(r'\1', s)
    s = s.strip('，。、 、.（）()_')
    return s.strip()


def extract_shot_assets_ordered(text: str) -> List:
    """返回当前分镜里带序号的资产名列表，元素为 (seq, name)，按图序/出现顺序排序。

    唯一来源 —— 图N 标记：
      图一：沈清辞 / 图1: 街道 / 图二为客厅 / 图一＝陈母 / 图五是客厅
    （注：本函数为旧接口，仅认图N；场景/物品裸名请用 extract_shot_assets_full）

    规则（用户明确）：
      - 只有以「图N」开头的行才纳入资产参考；
      - 正文里出现的人名/场景/物品（如「沈清辞撑着伞站在街角」）不提取，留给 AI 自行生成；
      - 资产：/参考图：/配图： 这类标签也不再作为资产来源。
      - 资产名会被清洗：去掉身高/括号/修饰词，只保留纯名字（如「沈清辞」）。
    seq 越小越靠前（图一 < 图二 …）。
    """
    out: List = []
    for r in _IMG_ASSET_RES:
        for m in r.finditer(text or ''):
            num = _cn_to_int(m.group(1))
            name = clean_asset_name(m.group(2))
            if name:
                out.append(((num if num is not None else 900), name))
    out.sort(key=lambda x: x[0])
    return out


def _clean_path_asset_name(path: str) -> str:
    """从文中内嵌的图片路径（如 人物设定/女主_小三形象_v1.png）提炼资产名。

    规则：
      - 取最后一级文件名，去扩展名；
      - 去掉版本号 _v1/_V2；
      - 去掉「_多角度场景 / _多角度道具」这类通用后缀，保留角色/造型主体，
        例如 「女主_小三形象_v1.png」→「女主_小三形象」，
        「高档餐厅_多角度场景_v1.png」→「高档餐厅」。
    """
    base = (path or '').replace('\\', '/').split('/')[-1]
    stem, _ = os.path.splitext(base)
    stem = re.sub(r'_v\d+$', '', stem, flags=re.I)
    # 去掉末尾的通用场景/道具描述
    stem = re.sub(r'_多角度(场景|道具)$', '', stem)
    # 去掉角色名后可能出现的重复造型描述（如 _形象_v1 已被版本号处理）
    return stem.strip(' _')


def extract_shot_assets_full(text: str) -> List:
    """返回 (seq, name, path_or_None) 列表，按图序排序。

    兼容多类写法：
      1) 图一：沈清辞 / 图1: 街道 / 图二为客厅 / 图一＝陈母 / 图五是客厅
         —— name 为纯名字，path=None（需后续模糊匹配）
      2) 图一对应F02 人物设定/女主_小三形象_v1.png —— name 从路径提炼，path 为文中路径片段
      3) 场景映射：客厅 / 物品映射：婚纱、戒指（无图N的裸名，显式资产声明，
         用户确认资产 = 人物 + 场景 + 物品；seq 800/850 排在人物之后）

    第 2 类写法里，图号后紧跟「对应F02」会被第 1 类的宽松正则误抓成名字「对应F02」，
    这里统一过滤掉以「对应」开头的垃圾名；同时以第 2 类解析出的 (seq,name,path) 为准。

    同一图号在「参考对应」「角色映射」多行重复出现时，按图号去重、先到先得
    （典型：图一＝陈母 在参考对应行和角色映射行各出现一次）。
    """
    # 先收集「图N对应路径」的 (seq -> (name, path))，作为权威来源
    ref_map: Dict[int, tuple] = {}
    for m in _IMG_REF_RES.finditer(text or ''):
        num = _cn_to_int(m.group(1))
        if num is None:
            continue
        path = m.group(2)
        name = _clean_path_asset_name(path)
        if name:
            ref_map[num] = (name, path)

    out: List = []
    seen_nums = set()
    for r in _IMG_ASSET_RES:
        for m in r.finditer(text or ''):
            num = _cn_to_int(m.group(1))
            raw = m.group(2)
            if raw.startswith('对应'):
                continue
            name = clean_asset_name(raw)
            if not name or name in _ASSET_NAME_BLACKLIST:
                continue
            if '无独立参考图' in name or '无参考图' in name:
                continue
            # 该图号若已有「对应路径」权威解析，则跳过宽松正则这条（避免重复/垃圾名）
            if num is not None and num in ref_map:
                continue
            # 同一图号只取第一次出现（参考对应/角色映射多行重复时去重）
            if num is not None:
                if num in seen_nums:
                    continue
                seen_nums.add(num)
            out.append(((num if num is not None else 900), name, None))

    for num, (name, path) in ref_map.items():
        out.append((num, name, path))

    # 场景/物品映射裸名（无图N）：显式资产声明，按名去重后追加（人物之后）
    seen_names = {n for (_s, n, _p) in out}
    for line_re, base_seq in _MAP_LINE_RES:
        for m in line_re.finditer(text or ''):
            chunk = m.group(1).strip().strip('*').strip()
            # 先剥掉括号内的场景描述（如「客厅（挑高六米、深色木质餐桌…）」），
            # 括号里是环境细节不是资产；未闭合左括号同样剥到行尾
            chunk = re.sub(r'[（(][^）)]*[)）]', '', chunk)
            chunk = re.sub(r'[（(][^）)]*$', '', chunk)
            for tok in re.split(r'[，,；;、\s]+', chunk):
                tok = tok.strip()
                if not tok or _TOKEN_IS_IMGN_RE.match(tok):
                    continue
                name = clean_asset_name(tok)
                if not name or name in _ASSET_NAME_BLACKLIST:
                    continue
                if '无独立参考图' in name or '无参考图' in name:
                    continue
                if name in seen_names:
                    continue
                seen_names.add(name)
                out.append((base_seq, name, None))

    out.sort(key=lambda x: x[0])
    return out



def norm_stem(path: str) -> str:
    """文件名（去扩展名、转小写、去空格），用于匹配。"""
    name = os.path.basename(path)
    stem, _ = os.path.splitext(name)
    return stem.strip().lower()


def read_text_file(path: str):
    """读取文本文件，返回 (文本, 编码)。兼容 UTF-8 / GBK。"""
    with open(path, 'rb') as f:
        raw = f.read()
    if b'\x00' in raw:
        raise ValueError('二进制文件，无法作为提示词打开')
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig'), 'utf-8-sig'
    for enc in ('utf-8', 'gb18030', 'gbk', 'latin-1'):
        try:
            return raw.decode(enc), enc
        except Exception:
            continue
    return raw.decode('utf-8', 'replace'), 'utf-8'
