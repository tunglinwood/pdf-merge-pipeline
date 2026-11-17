#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 4/4：校验合并结果与下载链接，产出最终实测报告。

用法：
    python3 scripts/verify_result.py --report merged_report.json --upload upload_result.json --out merged_result.json

校验项：
    1. 合并产物存在且页数 == 报告里的 total_pages；
    2. 合并产物逐页宽高 == 报告里的 merged_page_sizes（pt 级一致）；
    3. 交付链接是平台存储的长期链接（/api/system/file/d/...），不是沙箱 2 小时预览链接；
    4. 交付链接可打开，Content-Type 为 application/pdf 且内容以 %PDF 开头；
    5. 每个文件的页数/逐页宽高/失败原因齐全（失败文件必须带 error）。

最后输出一段 JSON：
    {"ok": true, "total_pages": 4, "merged_page_sizes": [...],
     "files": [{"name": ..., "pages": ..., "page_sizes_pt": [...], "status": "ok|failed", "error": null}],
     "download_link": "...", "checks": [{"name": ..., "ok": true, "detail": "..."}]}
"""

import argparse
import json
import urllib.request
from pathlib import Path


def log(message):
    print('[verify] {}'.format(message), flush=True)


def check(name, ok, detail):
    log('{} {} {}'.format('PASS' if ok else 'FAIL', name, detail))
    return {'name': name, 'ok': bool(ok), 'detail': detail}


def main():
    parser = argparse.ArgumentParser(description='步骤 4：校验合并结果与下载链接')
    parser.add_argument('--report', required=True, help='合并报告 merged_report.json')
    parser.add_argument('--upload', default='upload_result.json', help='上传中间结构 upload_result.json')
    parser.add_argument('--merged', default='merged.pdf', help='合并产物路径')
    parser.add_argument('--out', default='merged_result.json', help='最终报告输出路径')
    args = parser.parse_args()

    with open(args.report, 'r', encoding='utf-8') as handle:
        report = json.load(handle)
    upload = {}
    if Path(args.upload).exists():
        with open(args.upload, 'r', encoding='utf-8') as handle:
            upload = json.load(handle)

    checks = []

    merged_path = Path(args.merged)
    actual_sizes = []
    if merged_path.exists():
        from pypdf import PdfReader

        reader = PdfReader(str(merged_path))
        actual_sizes = [
            {'w': round(float(page.mediabox.width), 2), 'h': round(float(page.mediabox.height), 2)}
            for page in reader.pages
        ]
        checks.append(check('merged_exists', True, '合并产物存在：{}'.format(merged_path)))
        checks.append(check('total_pages_match',
                            len(reader.pages) == int(report.get('total_pages') or 0),
                            '产物页数 {} == 报告 total_pages {}'.format(len(reader.pages), report.get('total_pages'))))
        expected_sizes = report.get('merged_page_sizes') or []
        same = len(expected_sizes) == len(actual_sizes) and all(
            abs(float(a.get('w', 0)) - float(b.get('w', 0))) <= 0.5
            and abs(float(a.get('h', 0)) - float(b.get('h', 0))) <= 0.5
            for a, b in zip(expected_sizes, actual_sizes)
        )
        checks.append(check('page_sizes_match', same,
                            '逐页宽高与报告一致（{} 页）'.format(len(actual_sizes))))
    else:
        checks.append(check('merged_exists', False, '找不到合并产物：{}'.format(merged_path)))

    link = upload.get('download_link') or ''
    is_long_term = '/api/system/file/d/' in link and 'sandbox' not in link
    checks.append(check('download_link_is_long_term', is_long_term,
                        '交付链接形态：{}'.format(link or '(空)')))

    content_type = ''
    magic_ok = False
    size_ok = False
    if link:
        try:
            request = urllib.request.Request(link, method='GET')
            with urllib.request.urlopen(request, timeout=180) as response:
                content_type = response.headers.get('Content-Type') or ''
                body = response.read()
            magic_ok = body[:5] == b'%PDF-'
            size_ok = upload.get('size') is None or len(body) == int(upload['size'])
        except Exception as exc:
            content_type = '打开失败：{}'.format(exc)
        checks.append(check('download_link_openable', magic_ok,
                            'Content-Type={}，魔数={}，字节数一致={}'.format(content_type, magic_ok, size_ok)))
        checks.append(check('content_type_is_pdf', 'application/pdf' in content_type.lower(),
                            'Content-Type={}'.format(content_type)))

    # 一致性校验：合并结果必须等于各文件页序拼接（页序 = 上传顺序 × 文件内页序）。
    # 少了这一项，同名不同后缀的文件互相覆盖时不会被发现——
    # 报告与产物各自自洽，但产物内容是错的。
    files = report.get('files') or []
    expected_concat = [
        size
        for item in files
        if item.get('status') == 'ok'
        for size in (item.get('page_sizes_pt') or [])
    ]
    actual_concat = report.get('merged_page_sizes') or []
    concat_ok = len(expected_concat) == len(actual_concat) and all(
        abs(float(a.get('w', 0)) - float(b.get('w', 0))) <= 0.5
        and abs(float(a.get('h', 0)) - float(b.get('h', 0))) <= 0.5
        for a, b in zip(expected_concat, actual_concat)
    )
    checks.append(check('page_order_matches_files', concat_ok,
                        '合并逐页宽高等于各文件页序拼接：期望 {} 页，实际 {} 页'.format(
                            len(expected_concat), len(actual_concat))))


    missing = [item.get('name') for item in files
               if item.get('status') != 'ok' and not item.get('error')]
    checks.append(check('failed_files_named', not missing,
                        '失败文件都有原因：{}'.format(missing or '无失败文件')))
    incomplete = [item.get('name') for item in files
                  if item.get('status') == 'ok' and not item.get('page_sizes_pt')]
    checks.append(check('files_have_page_sizes', not incomplete,
                        '成功文件都有逐页宽高：{}'.format(incomplete or '齐全')))

    result = {
        'ok': all(item['ok'] for item in checks),
        'total_pages': report.get('total_pages'),
        'merged_page_sizes': actual_sizes or report.get('merged_page_sizes'),
        'files': files,
        'failed': report.get('failed') or [],
        'download_link': link,
        'filename': upload.get('filename'),
        'size': upload.get('size'),
        'checks': checks,
    }
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    if not result['ok']:
        raise SystemExit('校验未全部通过：{}'.format([c['name'] for c in checks if not c['ok']]))


if __name__ == '__main__':
    main()
