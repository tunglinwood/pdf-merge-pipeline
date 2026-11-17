#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入口脚本：转换（步骤 1）+ 合并（步骤 2），保持与既有命令兼容。

用法：
    python3 scripts/merge_to_pdf.py --input-list files.json --out merged.pdf --report merged_report.json

等价于依次执行：
    python3 scripts/convert_to_pdf.py --input-list files.json --out-dir converted --manifest convert_manifest.json
    python3 scripts/merge_pdfs.py --manifest convert_manifest.json --out merged.pdf --report merged_report.json

最后一行输出合并报告 JSON（total_pages / merged_page_sizes / files[].page_sizes_pt / failed）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convert_to_pdf  # noqa: E402  （同层扁平引用）
import merge_pdfs  # noqa: E402
import rules as rules_mod  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='逐个转 PDF 并按上传顺序合并')
    parser.add_argument('--input-list', required=True, help='有序文件清单（JSON 数组）')
    parser.add_argument('--out', required=True, help='合并输出 PDF 路径')
    parser.add_argument('--report', default=None, help='合并报告输出路径')
    parser.add_argument('--user-dir', default=None, help='上传文件目录，默认自动探测')
    parser.add_argument('--work-dir', default='converted', help='单文件 PDF 中间产物目录')
    parser.add_argument('--rules', default=None, help='规则配置文件路径，默认 config/page_rules.json')
    args = parser.parse_args()

    rules = rules_mod.load_rules(args.rules)
    with open(args.input_list, 'r', encoding='utf-8') as handle:
        items = json.load(handle)
    if isinstance(items, dict):
        items = items.get('files') or items.get('list') or []
    if not isinstance(items, list):
        raise SystemExit('input-list 必须是数组')

    max_files = int(rules.get('max_files') or 0)
    if max_files and len(items) > max_files:
        raise SystemExit('本轮文件数 {} 超过上限 {}'.format(len(items), max_files))

    user_dir = convert_to_pdf.detect_user_dir(args.user_dir)
    if not user_dir:
        raise SystemExit('找不到上传文件目录（user_files），请用 --user-dir 指定')
    convert_to_pdf.log('user files dir: {}'.format(user_dir))
    try:
        listing = sorted(p.name for p in Path(user_dir).iterdir() if p.is_file())
    except Exception:
        listing = []
    convert_to_pdf.log('directory listing: {}'.format(json.dumps(listing, ensure_ascii=False)))

    convert_to_pdf.ensure_pip([('pypdf', 'pypdf'), ('PIL', 'pillow'), ('img2pdf', 'img2pdf')])

    manifest = convert_to_pdf.convert_all(items, args.work_dir, user_dir, rules)
    manifest_path = Path(args.work_dir) / 'convert_manifest.json'
    with open(manifest_path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    report, ok = merge_pdfs.merge(manifest, args.out)
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    if not ok:
        raise SystemExit(rules_mod.message(rules, 'all_failed'))


if __name__ == '__main__':
    main()
