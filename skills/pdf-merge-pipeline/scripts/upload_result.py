#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 3/4：把合并结果上传到 FastGPT 存储，返回可直接打开的长期下载链接。

用法：
    python3 scripts/upload_result.py merged.pdf --filename 合并结果.pdf

凭据来自环境变量（用 `set -a; . ./config/pipeline.env; set +a` 载入）：
    FASTGPT_BASE_URL   平台地址，默认 https://x.huamedicine.com
    FASTGPT_API_TOKEN  平台 API Key

中间结构（步骤 4 用）：
    upload_result.json = {"download_link": "...", "filename": "合并结果.pdf", "size": 12345, "verified": true}

最后一行输出同一段 JSON。**只有 download_link 是给用户的交付链接**，
不要把 API Key、预签名上传地址（data.url）或脚本日志贴给用户。
"""

import argparse
import json
import mimetypes
import os
import urllib.request
from pathlib import Path


def log(message):
    print('[upload] {}'.format(message), flush=True)


def http_json(url, payload, headers=None):
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json', **(headers or {})}, method='POST'
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description='上传文件到 FastGPT 存储')
    parser.add_argument('path', help='本地文件路径')
    parser.add_argument('--filename', default=None, help='存储里的文件名')
    parser.add_argument('--base-url', default=None, help='FastGPT 地址')
    parser.add_argument('--out', default='upload_result.json', help='中间结构输出路径')
    args = parser.parse_args()

    source = Path(args.path)
    if not source.exists():
        raise SystemExit('文件不存在：{}'.format(source))

    base_url = (args.base_url or os.environ.get('FASTGPT_BASE_URL') or 'https://x.huamedicine.com').rstrip('/')
    token = (os.environ.get('FASTGPT_API_TOKEN') or '').strip()
    if not token:
        raise SystemExit('缺少 FASTGPT_API_TOKEN：请先载入技能目录下的 config/pipeline.env')

    filename = args.filename or source.name
    size = source.stat().st_size
    content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    presign = http_json(
        '{}/api/common/file/presignTempFilePostUrl'.format(base_url),
        {'filename': filename, 'size': size},
        {'Authorization': 'Bearer {}'.format(token)},
    )
    data = presign.get('data') or {}
    upload_url = data.get('url')
    if not upload_url:
        raise SystemExit('预签名失败：{}'.format(presign.get('message')))

    content = source.read_bytes()
    request = urllib.request.Request(
        upload_url,
        data=content,
        headers={'content-type': data.get('headers', {}).get('content-type', content_type)},
        method='PUT',
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        if response.status >= 300:
            raise SystemExit('上传失败：HTTP {}'.format(response.status))

    download_link = data.get('previewUrl') or data.get('url')
    verified = False
    try:
        with urllib.request.urlopen(download_link, timeout=180) as response:
            verified = len(response.read()) == size
    except Exception as exc:
        log('回下载校验失败：{}'.format(exc))

    result = {
        'download_link': download_link,
        'filename': filename,
        'size': size,
        'verified': verified,
        'content_type': content_type,
    }
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
