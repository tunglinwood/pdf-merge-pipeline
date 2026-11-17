#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdf-merge-pipeline 公共模块：加载可编辑配置（页面尺寸换算规则 / 文件类型白名单 / 失败原因文案）。

本模块与 scripts/ 同层（拍平），不使用 `from lib.x import` 形式，避免技能包多层嵌套导致 import 丢失。
配置来源：config/page_rules.json（可用 --rules 指定其它路径）；文件缺失时回落到内置默认值。
"""

import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_ROOT / 'config' / 'page_rules.json'

DEFAULT_RULES = {
    'version': 'builtin',
    'image': {'px_to_pt': 0.75, 'dpi': 96},
    'pdf': {'reuse_original_pages': True},
    'office': {'engine': 'libreoffice', 'keep_orientation': True},
    'max_files': 40,
    'supported_extensions': {
        'pdf': ['.pdf'],
        'image': ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tif', '.tiff'],
        'office': ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                   '.odt', '.ods', '.odp', '.rtf', '.wps', '.et', '.dps'],
    },
    'error_messages': {
        'missing_file': '沙箱里找不到文件：{name}（目录 {dir}）',
        'unsupported_type': '不支持的文件类型：{ext}（支持 pdf / 图片 / Office 文档）',
        'no_office_engine': '沙箱内没有 LibreOffice（soffice），无法按原页面设置转换 Office 文档',
        'office_convert_failed': 'LibreOffice 转换失败（exit={code}）：{detail}',
        'image_convert_failed': '图片转 PDF 失败：{detail}',
        'pdf_read_failed': 'PDF 读取失败：{detail}',
        'all_failed': '没有任何文件转换成功',
        'merge_failed': '合并失败：{detail}',
    },
}


def _deep_merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_rules(path=None):
    """读取配置；文件不存在或解析失败时回落到内置默认值。"""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    rules = json.loads(json.dumps(DEFAULT_RULES))
    if config_path.exists():
        try:
            user_rules = json.loads(config_path.read_text(encoding='utf-8'))
        except Exception:
            user_rules = {}
        rules = _deep_merge(rules, user_rules)
    rules['_config_path'] = str(config_path)
    return rules


def classify(ext, rules):
    """按白名单判定文件类别：pdf / image / office / None（不支持）。"""
    ext = str(ext or '').lower()
    table = rules.get('supported_extensions') or {}
    for kind in ('pdf', 'image', 'office'):
        if ext in [str(item).lower() for item in table.get(kind, [])]:
            return kind
    return None


def message(rules, key, **kwargs):
    """取失败原因文案（集中在配置文件里，可编辑）。"""
    texts = rules.get('error_messages') or {}
    template = texts.get(key) or key
    try:
        return template.format(**kwargs)
    except Exception:
        return template
