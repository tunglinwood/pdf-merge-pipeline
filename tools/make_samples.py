#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 B 线端到端实测用的样例文件（可复现）。

用法：
    python3 tools/make_samples.py [输出目录]

产出：
    会议纪要.png        1200×800 px 纯色图片（图片页期望 900×600 pt）
    文献综述.pdf        2 页：A4 纵向 + A5 横向（PDF 页原样沿用）
    汇报材料.docx       A5 纵向页面设置（Office 按自身页面设置转换）
    测试表格.xlsx       A4 横向（Excel 保留横向）
    测试幻灯片.pptx     16:9（PPT 保留自身比例）
    损坏文件.docx       伪造 zip 头的坏文件（触发「点名失败原因、其余继续合并」）
"""

import os
import struct
import sys
import zipfile
from pathlib import Path


def make_png(path, width, height):
    """不依赖第三方库手写一张纯色 PNG。

    PNG 的扫描线是「每行 1 个过滤字节 + width*3 字节 RGB」，
    行数必须正好是 height —— 按像素逐个换行会得到结构非法的 PNG
    （PIL 报 "unrecognized data stream contents"）。
    """
    import zlib

    rows = []
    for y in range(height):
        row = bytearray(b'\x00')
        for x in range(width):
            row += bytes(((x * 7) % 256, (y * 5) % 256, 128))
        rows.append(bytes(row))
    raw = b''.join(rows)

    def chunk(tag, data):
        payload = tag + data
        return struct.pack('>I', len(data)) + payload + struct.pack('>I', zlib.crc32(payload) & 0xffffffff)

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', header)
           + chunk(b'IDAT', zlib.compress(raw, 9))
           + chunk(b'IEND', b''))
    Path(path).write_bytes(png)


def make_pdf(path):
    """2 页 PDF：A4 纵向（595.28×841.89pt）+ A5 横向（841.89×595.28pt）。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for width, height in ((595.28, 841.89), (841.89, 595.28)):
        writer.add_blank_page(width=width, height=height)
    with open(path, 'wb') as handle:
        writer.write(handle)


def make_docx(path):
    from docx import Document
    from docx.shared import Twips

    document = Document()
    section = document.sections[0]
    section.page_width = Twips(8395)    # A5 纵向
    section.page_height = Twips(11909)
    document.add_heading('医学事务部 汇报材料', level=1)
    document.add_paragraph('本文件用于验证 Word 按自身页面设置转换并保留纸张方向。')
    document.save(path)


def make_xlsx(path):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet['A1'] = '医学事务部 横向表格测试'
    sheet['B1'] = 123
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    book.save(path)


def make_pptx(path):
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = '测试幻灯片 16:9'
    presentation.save(path)


def make_broken_docx(path):
    """伪造 zip 头，LibreOffice 无法加载。"""
    Path(path).write_bytes(b'PK\x03\x04' + b'not-a-real-docx' * 8)


def make_same_stem_samples(out):
    """同名不同后缀的三个文件（回归用例：中间产物不得互相覆盖）。

    期望合并后 4 页，页序 = 上传顺序 × 文件内页序：
        同名素材.png   1 页 800×1200 px → 600×900 pt
        同名素材.pdf   2 页 400×600、595.28×841.89 pt（原样沿用）
        同名素材.docx  1 页 A4 横向 → 841.89×595.28 pt
    """
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Mm
    from pypdf import PdfWriter

    make_png(out / '同名素材.png', 800, 1200)

    writer = PdfWriter()
    for width, height in ((400, 600), (595.28, 841.89)):
        writer.add_blank_page(width=width, height=height)
    with open(out / '同名素材.pdf', 'wb') as handle:
        writer.write(handle)

    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Mm(297)
    section.page_height = Mm(210)
    document.add_heading('同名不同后缀的 docx', level=1)
    document.save(out / '同名素材.docx')


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else 'samples')
    out.mkdir(parents=True, exist_ok=True)
    make_png(out / '会议纪要.png', 1200, 800)
    make_pdf(out / '文献综述.pdf')
    make_docx(out / '汇报材料.docx')
    make_xlsx(out / '测试表格.xlsx')
    make_pptx(out / '测试幻灯片.pptx')
    make_broken_docx(out / '损坏文件.docx')
    make_same_stem_samples(out)
    print('样例文件已生成到 {}'.format(out.resolve()))


if __name__ == '__main__':
    main()
