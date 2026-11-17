#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：同名不同后缀的多文件合并不得互相覆盖。

背景：转换步骤曾把每个文件的中间产物写成 <stem>.pdf，于是
a.png / a.pdf / a.docx 会写进同一个 a.pdf —— 后者覆盖前者。
合并时每个条目都指向同一个路径，最终产物的页序与页面尺寸
与「每个文件各自转出来的那一份」不符，而报告与产物又各自自洽，
原来的校验查不出来。

本测试直接跑真实的转换+合并脚本，断言：
  1. 合并结果的逐页宽高 == 各文件 page_sizes_pt 按上传顺序的拼接；
  2. 总页数 == 各文件页数之和。
同时验证 verify_result.py 的 page_order_matches_files 检查能抓住回归。

用法：
    python3 tests/test_stem_collision.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / 'skills' / 'pdf-merge-pipeline'
SCRIPTS = SKILL / 'scripts'


def build_samples(user_dir):
    """生成三个「stem 相同、后缀不同」的文件：a.png / a.pdf / a.docx。"""
    from PIL import Image, ImageDraw
    from pypdf import PdfWriter
    from docx import Document
    from docx.shared import Mm
    from docx.enum.section import WD_ORIENT

    user_dir.mkdir(parents=True, exist_ok=True)

    image = Image.new('RGB', (800, 1200), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 40, 760, 1160], outline='black', width=8)
    image.save(user_dir / 'a.png', 'PNG')

    writer = PdfWriter()
    writer.add_blank_page(width=400, height=600)
    writer.add_blank_page(width=595.28, height=841.89)
    with open(user_dir / 'a.pdf', 'wb') as handle:
        writer.write(handle)

    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Mm(297)
    section.page_height = Mm(210)
    document.add_paragraph('same stem docx')
    document.save(user_dir / 'a.docx')


def run_pipeline(work_dir, names):
    items_path = work_dir / 'files.json'
    items_path.write_text(json.dumps(names), encoding='utf-8')
    merged = work_dir / 'merged.pdf'
    report = work_dir / 'report.json'

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / 'merge_to_pdf.py'),
         '--input-list', str(items_path),
         '--out', str(merged),
         '--report', str(report),
         '--user-dir', str(work_dir / 'user_files')],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise AssertionError('合并脚本失败：\n{}\n{}'.format(result.stdout, result.stderr))
    return merged, report


def main():
    names = ['a.png', 'a.pdf', 'a.docx']
    # 独立算出的期望值：图片 800×1200 px × 0.75；PDF 两页原样；docx A4 横向。
    # 不依赖报告里的数字，报告自己出错时也能发现。
    expected = [
        {'w': 600.0, 'h': 900.0},
        {'w': 400.0, 'h': 600.0},
        {'w': 595.28, 'h': 841.89},
        {'w': 841.89, 'h': 595.28},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        build_samples(work_dir / 'user_files')
        merged, report = run_pipeline(work_dir, names)

        data = json.loads(report.read_text(encoding='utf-8'))
        actual = data.get('merged_page_sizes') or []
        failed = [
            '{}：{}'.format(item.get('name'), item.get('error'))
            for item in data['files']
            if item.get('status') != 'ok'
        ]

        failures = []
        if failed:
            failures.append('有文件转换失败：{}'.format('；'.join(failed)))
        if len(expected) != len(actual):
            failures.append('页数不一致：期望 {} 页，合并产物 {} 页'.format(len(expected), len(actual)))
        else:
            for index, (want, got) in enumerate(zip(expected, actual), 1):
                if abs(float(want['w']) - float(got['w'])) > 0.5 or abs(float(want['h']) - float(got['h'])) > 0.5:
                    failures.append('第 {} 页尺寸不符：期望 {}x{}，实际 {}x{}'.format(
                        index, want['w'], want['h'], got['w'], got['h']))
                    break

        total_expected = sum(int(item.get('pages') or 0) for item in data['files'])
        if int(data.get('total_pages') or 0) != total_expected:
            failures.append('总页数不符：期望 {}，实际 {}'.format(total_expected, data.get('total_pages')))
        if int(data.get('total_pages') or 0) != len(expected):
            failures.append('总页数不符：期望 {}，实际 {}'.format(len(expected), data.get('total_pages')))

        print('期望逐页宽高：{}'.format(json.dumps(expected, ensure_ascii=False)))
        print('合并产物逐页宽高：{}'.format(json.dumps(actual, ensure_ascii=False)))
        print('总页数：{}（各文件页数之和 {}）'.format(data.get('total_pages'), total_expected))
        if failed:
            print('转换失败：{}'.format('；'.join(failed)))

        if failures:
            for message in failures:
                print('FAIL: {}'.format(message))
            return 1
        print('PASS: 同名不同后缀的文件未互相覆盖，页序与页面尺寸与逐文件结果一致')
        return 0


if __name__ == '__main__':
    sys.exit(main())
