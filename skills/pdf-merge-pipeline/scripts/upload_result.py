#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 3/4：把合并结果上传到 FastGPT 存储，返回可直接打开的下载链接。

用法：
    python3 scripts/upload_result.py merged.pdf --filename 合并结果.pdf [--chat-id <对话ID>]

凭据来自环境变量（用 `set -a; . ./config/pipeline.env; set +a` 载入）：
    FASTGPT_BASE_URL   平台地址，默认 https://x.huamedicine.com
    FASTGPT_API_TOKEN  平台 API Key
    FASTGPT_APP_ID     工作流应用 ID（把文件存进对话时需要）

中间结构（步骤 4 用）：
    upload_result.json = {"download_link": "...", "filename": "合并结果.pdf", "size": 12345,
                          "storage": "chat", "chat_id": "...", "verified": true}

**存储位置很关键**：
    1) 优先存成「对话文件」（chat file）：文件挂在本次对话下，平台随时可以重新签发下载链接，
       用户在自己的会话里长期能取到；
    2) 拿不到 appId / chatId 时退回「临时文件」（temp file）：链接带时效，先验后仍会过期。

最后一行输出同一段 JSON。**只有 download_link 是给用户的交付链接**，
不要把 API Key、预签名上传地址（data.url）或脚本日志贴给用户。
"""

import argparse
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

SESSIONS_DIR = '/workspace/sessions'


def log(message):
    print('[upload] {}'.format(message), flush=True)


def http_json(url, payload, headers=None):
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json', **(headers or {})}, method='POST'
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode('utf-8'))


def detect_chat_id():
    """从沙箱会话目录里推断当前对话 ID（沙箱工作目录名就是对话 ID）。"""
    root = Path(SESSIONS_DIR)
    if not root.is_dir():
        return None
    sessions = [item for item in root.iterdir() if item.is_dir()]
    if not sessions:
        return None
    sessions.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    log('自动探测对话 ID：{}（来自 {}）'.format(sessions[0].name, SESSIONS_DIR))
    return sessions[0].name


def put_file(upload_url, payload, content_type):
    request = urllib.request.Request(
        upload_url,
        data=payload,
        headers={'content-type': content_type},
        method='PUT',
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        if response.status >= 300:
            raise RuntimeError('上传失败：HTTP {}'.format(response.status))


def upload_chat_file(base_url, token, source, filename, size, content_type, app_id, chat_id):
    """存成对话文件：文件挂在本次对话下，平台可随时重新签发链接。"""
    presign = http_json(
        '{}/api/core/chat/file/presignChatFilePostUrl'.format(base_url),
        {
            'appId': app_id,
            'chatId': chat_id,
            'filename': filename,
            'contentType': content_type,
            'size': size,
        },
        {'Authorization': 'Bearer {}'.format(token)},
    )
    data = presign.get('data') or {}
    upload_url = data.get('url')
    if not upload_url:
        raise RuntimeError('对话文件预签名失败：{}'.format(presign.get('message')))
    put_file(upload_url, source.read_bytes(), data.get('headers', {}).get('content-type', content_type))
    return data.get('previewUrl') or data.get('url'), data.get('key')


def upload_temp_file(base_url, token, source, filename, size, content_type):
    """退回临时文件：链接有时效（平台预签名有效期 1 小时量级）。"""
    presign = http_json(
        '{}/api/common/file/presignTempFilePostUrl'.format(base_url),
        {'filename': filename, 'size': size},
        {'Authorization': 'Bearer {}'.format(token)},
    )
    data = presign.get('data') or {}
    upload_url = data.get('url')
    if not upload_url:
        raise RuntimeError('临时文件预签名失败：{}'.format(presign.get('message')))
    put_file(upload_url, source.read_bytes(), data.get('headers', {}).get('content-type', content_type))
    return data.get('previewUrl') or data.get('url'), data.get('key')


def main():
    parser = argparse.ArgumentParser(description='上传合并结果到 FastGPT 存储')
    parser.add_argument('path', help='本地文件路径')
    parser.add_argument('--filename', default=None, help='存储里的文件名')
    parser.add_argument('--base-url', default=None, help='FastGPT 地址')
    parser.add_argument('--app-id', default=None, help='工作流应用 ID（默认取 FASTGPT_APP_ID）')
    parser.add_argument('--chat-id', default=None, help='对话 ID（默认取 FASTGPT_CHAT_ID 或自动探测）')
    parser.add_argument('--out', default='upload_result.json', help='中间结构输出路径')
    parser.add_argument('--temp-only', action='store_true', help='只走临时文件上传（不推荐）')
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
    app_id = (args.app_id or os.environ.get('FASTGPT_APP_ID') or '').strip()
    chat_id = (args.chat_id or os.environ.get('FASTGPT_CHAT_ID') or '').strip()
    if not chat_id and not args.temp_only:
        chat_id = detect_chat_id() or ''

    download_link = None
    storage = None
    key = None
    if app_id and chat_id and not args.temp_only:
        try:
            download_link, key = upload_chat_file(
                base_url, token, source, filename, size, content_type, app_id, chat_id
            )
            storage = 'chat'
        except Exception as exc:
            log('对话文件上传失败（{}），退回临时文件：{}'.format(type(exc).__name__, exc))
            download_link = None
    if not download_link:
        download_link, key = upload_temp_file(base_url, token, source, filename, size, content_type)
        storage = 'temp'

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
        'storage': storage,
        'app_id': app_id if storage == 'chat' else None,
        'chat_id': chat_id if storage == 'chat' else None,
    }
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
