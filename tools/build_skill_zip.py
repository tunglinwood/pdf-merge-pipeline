#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把技能包目录打成平台可导入的 zip。

用法：
    python3 tools/build_skill_zip.py --source skills/pdf-merge-pipeline \
        --env /path/to/pipeline.env --out pdf-merge-pipeline-v1.2.zip

约定：
    * zip 内路径固定为 skills/pdf-merge-pipeline/...（平台按此结构解包）；
    * config/pipeline.env 从 --env 单独带入（里面是沙箱用的凭据，不入库、不进 git）；
    * __pycache__ / *.pyc 一律排除；
    * 其余文件（SKILL.md / scripts / config）全部来自 --source，逐字复制。
"""

import argparse
import os
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {'__pycache__', '.git'}
EXCLUDE_SUFFIX = ('.pyc', '.pyo')


def collect(source):
    files = []
    for root, dirs, names in os.walk(source):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in sorted(names):
            if name.endswith(EXCLUDE_SUFFIX):
                continue
            path = Path(root) / name
            # zip 内固定为 skills/<技能名>/...（平台按此结构解包）
            files.append((path, Path('skills') / source.name / path.relative_to(source)))
    return files


def main():
    parser = argparse.ArgumentParser(description='打包 FastGPT 技能包')
    parser.add_argument('--source', required=True, help='技能目录（其父目录为 zip 内的 skills/）')
    parser.add_argument('--env', required=True, help='config/pipeline.env 的来源文件（凭据不入库）')
    parser.add_argument('--out', required=True, help='输出 zip 路径')
    args = parser.parse_args()

    source = Path(args.source).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    files = collect(source)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path, arc in files:
            if path.name == 'pipeline.env':
                continue  # 凭据文件单独带入
            bundle.write(path, str(arc))
        bundle.write(Path(args.env).resolve(), str(Path('skills/pdf-merge-pipeline/config/pipeline.env')))

    with zipfile.ZipFile(out) as bundle:
        names = bundle.namelist()
    print('打包完成：{}（{} 个文件）'.format(out, len(names)))
    for name in names:
        print('  {}'.format(name))


if __name__ == '__main__':
    main()
