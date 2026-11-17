#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 2/4：按上传顺序把步骤 1 产出的单文件 PDF 合并成一个 PDF。

用法：
    python3 scripts/merge_pdfs.py --manifest convert_manifest.json --out merged.pdf --report merged_report.json

页序规则：页序 = 文件上传顺序 × 文件内页序；各文件的页面尺寸互不影响（原样搬运页面对象）。

中间结构：
    merged_report.json = {
      "ok": true,
      "total_pages": 4,
      "merged_page_sizes": [{"w": 900.0, "h": 600.0}, ...],
      "files": [{"name": ..., "pages": 1, "page_sizes_pt": [...], "status": "ok", "error": null}, ...],
      "failed": [...]
    }
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules as rules_mod  # noqa: E402


def log(message):
    print('[merge] {}'.format(message), flush=True)


def merge(manifest, out_path):
    """按清单顺序合并；失败的条目跳过并保留原因。"""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    files = []
    for entry in manifest.get('files', []):
        record = {
            'name': entry.get('name'),
            'kind': entry.get('kind'),
            'status': entry.get('status'),
            'pages': entry.get('pages', 0),
            'page_sizes_pt': entry.get('page_sizes_pt', []),
            'error': entry.get('error'),
        }
        if entry.get('status') != 'ok':
            record['status'] = 'failed'
            files.append(record)
            continue
        pdf_path = Path(entry.get('pdf_path'))
        if not pdf_path.exists():
            record['status'] = 'failed'
            record['error'] = '转换产物不存在：{}'.format(pdf_path)
            files.append(record)
            continue
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            writer.add_page(page)
        files.append(record)

    ok_files = [item for item in files if item['status'] == 'ok']
    if not ok_files:
        report = {
            'ok': False,
            'total_pages': 0,
            'merged_page_sizes': [],
            'files': files,
            'failed': files,
            'error': '没有任何文件转换成功',
        }
        return report, False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'wb') as handle:
        writer.write(handle)

    merged_reader = PdfReader(str(out_path))
    merged_sizes = [
        {'w': round(float(page.mediabox.width), 2), 'h': round(float(page.mediabox.height), 2)}
        for page in merged_reader.pages
    ]
    report = {
        'ok': True,
        'merged': str(out_path),
        'total_pages': len(merged_reader.pages),
        'merged_page_sizes': merged_sizes,
        'files': files,
        'failed': [item for item in files if item['status'] != 'ok'],
    }
    log('merged {} files -> {} pages {}'.format(len(ok_files), report['total_pages'], merged_sizes))
    return report, True


def main():
    parser = argparse.ArgumentParser(description='步骤 2：按上传顺序合并 PDF')
    parser.add_argument('--manifest', required=True, help='步骤 1 的中间结构 convert_manifest.json')
    parser.add_argument('--out', required=True, help='合并输出 PDF 路径')
    parser.add_argument('--report', default=None, help='合并报告输出路径')
    parser.add_argument('--rules', default=None, help='规则配置文件路径')
    args = parser.parse_args()

    rules = rules_mod.load_rules(args.rules)
    with open(args.manifest, 'r', encoding='utf-8') as handle:
        manifest = json.load(handle)

    report, ok = merge(manifest, args.out)
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    if not ok:
        raise SystemExit(rules_mod.message(rules, 'all_failed'))


if __name__ == '__main__':
    main()
