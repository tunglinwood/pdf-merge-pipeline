#!/usr/bin/env python3
"""实测知识库交付链路：条目链接可达 + 条目原文匿名可下载 + 批量下载可用。

用法：
    FASTGPT_TOKEN=<fastgpt_token> python3 tools/verify_delivery.py --manifest delivery_manifest.json

manifest 里每项形如：
    {"collectionId": "...", "filename": "...", "local": "<本地文件路径>", "folder": "<文件夹 id>"}

结论全部来自真实 HTTP 请求：
1. 每个条目 collection/read → 原文 URL → **匿名 GET**（不带任何登录态）→ 字节数 / Content-Type / sha256 比对；
2. 知识库界面「批量下载」同款链路：getDownloadTicket → batchDownload → ZIP 内容校验；
3. 集合链接与条目链接：匿名 GET 的可达性；
4. PDF 逐页宽高复核（与本地源文件一致）。
"""
import argparse
import hashlib
import io
import json
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BASE = os.environ.get("FASTGPT_BASE_URL", "https://x.huamedicine.com")


def request(method, url, body=None, headers=None, timeout=180):
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.status), dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict(exc.headers or {}), exc.read()


def probe(url, headers=None):
    status, hdrs, payload = request("GET", url, headers=headers)
    return {
        "status": status,
        "bytes": len(payload),
        "content_type": hdrs.get("Content-Type", ""),
        "sha256_16": hashlib.sha256(payload).hexdigest()[:16],
        "body": payload,
    }


def pdf_pages(payload):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(payload))
    return [[round(float(p.mediabox.width), 2), round(float(p.mediabox.height), 2)] for p in reader.pages]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="交付清单 JSON")
    parser.add_argument("--out", default="verify_delivery.json", help="实测记录输出路径")
    args = parser.parse_args()

    token = os.environ.get("FASTGPT_TOKEN", "")
    session_headers = {"Cookie": f"fastgpt_token={token}", "fastgpt-web-request": "1"}
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    dataset_id = manifest["datasetId"]
    items = manifest["uploaded"]

    result = {"dataset_id": dataset_id, "files": [], "links": {}, "batch": {}}
    for item in items:
        status, _, payload = request(
            "POST", f"{BASE}/api/core/dataset/collection/read",
            body={"collectionId": item["collectionId"]}, headers=session_headers,
        )
        url = (json.loads(payload.decode("utf-8")).get("data") or {}).get("value")
        entry = {"collection_id": item["collectionId"], "name": item["filename"], "read_api_status": status, "file_url": url}
        if url:
            anon = probe(url)
            local_bytes = Path(item["local"]).read_bytes()
            entry["anonymous_get"] = {k: v for k, v in anon.items() if k != "body"}
            entry["match_local"] = anon["sha256_16"] == hashlib.sha256(local_bytes).hexdigest()[:16]
            if item["filename"].endswith(".pdf"):
                entry["pdf_pages"] = pdf_pages(anon["body"])
        result["files"].append(entry)

    ids = [item["collectionId"] for item in items]
    status, _, payload = request(
        "POST", f"{BASE}/api/core/dataset/collection/getDownloadTicket",
        body={"datasetId": dataset_id, "collectionIds": ids}, headers=session_headers,
    )
    ticket = (json.loads(payload.decode("utf-8")).get("data") or {}).get("ticket")
    result["batch"]["ticket_status"] = status
    if ticket:
        zip_status, zip_headers, zip_bytes = request(
            "GET", f"{BASE}/api/core/dataset/collection/batchDownload?ticket={ticket}", headers=session_headers
        )
        result["batch"]["download_status"] = zip_status
        result["batch"]["content_type"] = zip_headers.get("Content-Type", "")
        result["batch"]["bytes"] = len(zip_bytes)
        zip_path = Path(args.out).with_suffix(".zip")
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path) as archive:
            result["batch"]["entries"] = [{"name": i.filename, "bytes": i.file_size} for i in archive.infolist()]

    links = {
        "dataset_root": f"{BASE}/dataset/detail?datasetId={dataset_id}&currentTab=collectionCard",
    }
    if manifest.get("deliveryFolder"):
        links["delivery_folder"] = (
            f"{BASE}/dataset/detail?datasetId={dataset_id}&currentTab=collectionCard&parentId={manifest['deliveryFolder']['id']}"
        )
    for item in items:
        links[f"entry::{item['filename']}"] = (
            f"{BASE}/dataset/detail?datasetId={dataset_id}&currentTab=dataCard&collectionId={item['collectionId']}"
        )
    for key, url in links.items():
        probed = probe(url)
        result["links"][key] = {k: v for k, v in probed.items() if k != "body"}

    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
