#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 1/4：把本轮上传的每个文件逐个转成 PDF（保持原页面大小）。

用法：
    python3 scripts/convert_to_pdf.py --input-list files.json --out-dir converted --manifest convert_manifest.json

中间结构（步骤间传递用）：
    convert_manifest.json = {
      "ok": true,
      "files": [
        {"index": 1, "name": "会议纪要.png", "status": "ok", "kind": "image",
         "pages": 1, "page_sizes_pt": [{"w": 900.0, "h": 600.0}],
         "pdf_path": "converted/会议纪要.pdf", "error": null}
      ]
    }

页面大小口径全部来自 config/page_rules.json（可编辑）：
    PDF        —— 原样沿用原页面尺寸与方向
    图片       —— 单页，页面宽高 = 像素宽高 × px_to_pt（默认 0.75），不缩放、不裁剪、不加白边
    Office 文档 —— headless LibreOffice 按文档自身页面设置转换，保留纸张方向

失败容错：单个文件转换失败时记录文件名与原因，继续处理其余文件。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules as rules_mod  # noqa: E402  （与本脚本同层，扁平引用）


def log(message):
    print('[convert] {}'.format(message), flush=True)


def ensure_pip(packages):
    """按需安装依赖（PEP 668 环境需要 --break-system-packages）。"""
    missing = []
    for module, package in packages:
        try:
            __import__(module)
        except Exception:
            missing.append(package)
    if not missing:
        return True
    cmd = [sys.executable, '-m', 'pip', 'install', '--break-system-packages', '-q'] + missing
    log('installing deps: {}'.format(' '.join(missing)))
    try:
        subprocess.run(cmd, check=True, timeout=300)
        return True
    except Exception as exc:
        log('pip install failed: {}'.format(exc))
        return False


def safe_basename(name, index=0):
    """复刻平台把上传文件写进 user_files/ 时的文件名清洗规则。"""
    base = str(name or '').replace('\\', '/').split('/')[-1].strip()
    base = ''.join(ch for ch in base if ord(ch) >= 32 and ord(ch) != 127).strip()
    if not base or base in ('.', '..'):
        base = 'file-{}'.format(index)
    return base


def resolve_source(item, user_dir, index, rules):
    """把输入项解析成沙箱里的真实文件路径。"""
    if isinstance(item, str):
        name, explicit = item, None
    elif isinstance(item, dict):
        explicit = item.get('path') or item.get('sandboxPath')
        name = item.get('name') or (explicit.split('/')[-1] if explicit else '')
    else:
        name, explicit = str(item), None

    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = Path(user_dir) / candidate
        if candidate.exists():
            return candidate
        alt = Path(user_dir) / Path(explicit).name
        if alt.exists():
            return alt

    base = safe_basename(name, index)
    user_path = Path(user_dir)
    if user_path.exists():
        stem, ext = os.path.splitext(base)
        if (user_path / base).exists():
            return user_path / base
        for n in range(1, 20):
            alt = user_path / '{}-{}{}'.format(stem, n, ext)
            if alt.exists():
                return alt

    if name:
        raise FileNotFoundError(rules_mod.message(rules, 'missing_file', name=name, dir=user_dir))
    raise FileNotFoundError('输入项 {} 没有可用的文件名'.format(index))


def page_sizes(reader):
    """逐页宽高（pt），四舍五入到 2 位小数。"""
    sizes = []
    for page in reader.pages:
        box = page.mediabox
        sizes.append({'w': round(float(box.width), 2), 'h': round(float(box.height), 2)})
    return sizes


def convert_pdf(src, out_dir, rules):
    """PDF：原样沿用每一页。"""
    from pypdf import PdfReader, PdfWriter

    try:
        reader = PdfReader(str(src))
    except Exception as exc:
        raise RuntimeError(rules_mod.message(rules, 'pdf_read_failed', detail=exc))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    out = out_dir / (src.stem + '.pdf')
    with open(out, 'wb') as handle:
        writer.write(handle)
    return out, len(reader.pages), page_sizes(reader)


def convert_image(src, out_dir, rules):
    """图片：单页，页面宽高 = 像素宽高 × px_to_pt，不缩放、不裁剪、不加白边。"""
    from PIL import Image

    px_to_pt = float((rules.get('image') or {}).get('px_to_pt', 0.75))
    dpi = int((rules.get('image') or {}).get('dpi', round(72.0 / px_to_pt)))
    out = out_dir / (src.stem + '.pdf')
    try:
        with Image.open(str(src)) as image:
            if image.mode not in ('RGB', 'RGBA', 'L', 'LA'):
                image = image.convert('RGB')
            pixel_size = image.size
            normalized = out_dir / (src.stem + '.normalized.png')
            # 归一化 DPI：源图自带的 DPI 元数据不得影响页面尺寸
            image.save(str(normalized), 'PNG', dpi=(dpi, dpi))
            expected = (round(pixel_size[0] * px_to_pt, 2), round(pixel_size[1] * px_to_pt, 2))
            written = False
            try:
                import img2pdf

                with open(out, 'wb') as handle:
                    handle.write(img2pdf.convert(str(normalized)))
                written = True
            except Exception as exc:
                log('img2pdf 不可用或失败({})，改用 Pillow'.format(exc))
            if not written:
                with Image.open(str(normalized)) as image:
                    image.save(str(out), 'PDF', resolution=float(dpi))
    except Exception as exc:
        raise RuntimeError(rules_mod.message(rules, 'image_convert_failed', detail=exc))

    from pypdf import PdfReader

    reader = PdfReader(str(out))
    sizes = page_sizes(reader)
    expected = (round(pixel_size[0] * px_to_pt, 2), round(pixel_size[1] * px_to_pt, 2))
    actual = (sizes[0]['w'], sizes[0]['h']) if sizes else (0.0, 0.0)
    if abs(actual[0] - expected[0]) > 0.5 or abs(actual[1] - expected[1]) > 0.5:
        raise RuntimeError('图片页面尺寸与换算值不符：期望 {}×{} pt，实际 {}×{} pt'.format(
            expected[0], expected[1], actual[0], actual[1]))
    return out, len(reader.pages), sizes


def find_soffice():
    for candidate in ('soffice', 'libreoffice'):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def convert_office(src, out_dir, rules):
    """Office：headless LibreOffice 按文档自身页面设置转换，保留纸张方向。"""
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError(rules_mod.message(rules, 'no_office_engine'))

    with tempfile.TemporaryDirectory() as profile:
        cmd = [
            soffice,
            '--headless',
            '--norestore',
            '-env:UserInstallation=file://{}'.format(profile),
            '--convert-to',
            'pdf:writer_pdf_Export',
            '--outdir',
            str(out_dir),
            str(src),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
    produced = out_dir / (src.stem + '.pdf')
    if not produced.exists():
        raw = (proc.stdout or proc.stderr or '').strip()
        # 去掉 LibreOffice 的无害告警行（如 javaldx），只保留真正的失败原因
        lines = [line.strip() for line in raw.splitlines()
                 if line.strip() and not line.strip().lower().startswith('warning:')]
        detail = ' / '.join(lines[-2:])[:300] if lines else raw[:300]
        raise RuntimeError(rules_mod.message(rules, 'office_convert_failed', code=proc.returncode, detail=detail))
    from pypdf import PdfReader

    reader = PdfReader(str(produced))
    return produced, len(reader.pages), page_sizes(reader)


def convert_one(src, out_dir, rules):
    ext = src.suffix.lower()
    kind = rules_mod.classify(ext, rules)
    if kind == 'pdf':
        return 'pdf', convert_pdf(src, out_dir, rules)
    if kind == 'image':
        return 'image', convert_image(src, out_dir, rules)
    if kind == 'office':
        return 'office', convert_office(src, out_dir, rules)
    raise RuntimeError(rules_mod.message(rules, 'unsupported_type', ext=ext or '(无扩展名)'))


def detect_user_dir(explicit=None):
    if explicit:
        return explicit
    for candidate in ('user_files', '/workspace/user_files'):
        if Path(candidate).is_dir():
            return candidate
    here = Path.cwd()
    for parent in [here] + list(here.parents):
        candidate = parent / 'user_files'
        if candidate.is_dir():
            return str(candidate)
    return None


def convert_all(items, out_dir, user_dir, rules):
    """把清单里的每个文件转成 PDF，返回中间结构 manifest。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, item in enumerate(items):
        label = item if isinstance(item, str) else (item.get('name') or '<未命名>')
        entry = {
            'index': index + 1,
            'name': label,
            'status': 'ok',
            'kind': None,
            'pages': 0,
            'page_sizes_pt': [],
            'pdf_path': None,
            'error': None,
        }
        try:
            src = resolve_source(item, user_dir, index, rules)
            entry['source_path'] = str(src)
            kind, (pdf_path, pages, sizes) = convert_one(src, out_dir, rules)
            entry['kind'] = kind
            entry['pages'] = pages
            entry['page_sizes_pt'] = sizes
            entry['pdf_path'] = str(pdf_path)
            log('converted #{} {} -> {} pages {}'.format(index + 1, label, pages, sizes))
        except Exception as exc:
            entry['status'] = 'failed'
            entry['error'] = '{}: {}'.format(type(exc).__name__, exc)
            log('FAILED #{} {} -> {}'.format(index + 1, label, entry['error']))
        results.append(entry)
    return {
        'ok': any(item['status'] == 'ok' for item in results),
        'rules_version': rules.get('version'),
        'image_px_to_pt': (rules.get('image') or {}).get('px_to_pt'),
        'files': results,
    }


def main():
    parser = argparse.ArgumentParser(description='步骤 1：逐个转 PDF（保持页面大小）')
    parser.add_argument('--input-list', required=True, help='有序文件清单（JSON 数组）')
    parser.add_argument('--out-dir', default='converted', help='单文件 PDF 输出目录')
    parser.add_argument('--manifest', default='convert_manifest.json', help='中间结构输出路径')
    parser.add_argument('--user-dir', default=None, help='上传文件目录，默认自动探测')
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

    user_dir = detect_user_dir(args.user_dir)
    if not user_dir:
        raise SystemExit('找不到上传文件目录（user_files），请用 --user-dir 指定')
    log('user files dir: {}'.format(user_dir))
    try:
        listing = sorted(p.name for p in Path(user_dir).iterdir() if p.is_file())
    except Exception:
        listing = []
    log('directory listing: {}'.format(json.dumps(listing, ensure_ascii=False)))

    ensure_pip([('pypdf', 'pypdf'), ('PIL', 'pillow'), ('img2pdf', 'img2pdf')])

    manifest = convert_all(items, args.out_dir, user_dir, rules)
    if args.manifest:
        with open(args.manifest, 'w', encoding='utf-8') as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
