#!/usr/bin/env node
/**
 * 把 B 线交付物上传进 FastGPT 知识库的文件集合（交付用知识库，不是临时直链）。
 *
 * 用法：
 *   node tools/upload_delivery.mjs --dataset <datasetId> --folder "<文件夹名>" \
 *        --file "<本地路径>::<知识库里的文件名>" [--file ...]
 *
 * 关键点：条目用 trainingType=backup（只存文件、不做向量训练）。
 * 默认 chunk 模式对「几乎无文本层」的合并 PDF 会训练失败，条目在 collection/read 上直接
 * 返回 501003 unExistCollection（列表看得到、下载打不开）。
 *
 * 依赖：本机 fastgpt-mcp（提供 FastGPTSession）与 ~/.config/fastgpt-mcp/env 的平台会话配置。
 */
import { readFileSync } from 'node:fs';
import { basename } from 'node:path';

const MCP_SESSION = process.env.FASTMCP_SESSION ?? '/home/huasmex/workspace/fastgpt-mcp/dist/session.js';
const MCP_ENV = process.env.FASTMCP_ENV ?? '/home/huasmex/.config/fastgpt-mcp/env';
const MCP_CONFIG = process.env.FASTMCP_CONFIG ?? '/home/huasmex/workspace/fastgpt-mcp/config/config.json';

const { FastGPTSession } = await import(MCP_SESSION);
const env = Object.fromEntries(
  readFileSync(MCP_ENV, 'utf8').split('\n').filter((l) => l.includes('=')).map((l) => {
    const i = l.indexOf('=');
    return [l.slice(0, i).trim(), l.slice(i + 1).trim()];
  })
);
const cfg = JSON.parse(readFileSync(MCP_CONFIG, 'utf8'));
const session = new FastGPTSession({ ...cfg, passwordDigest: env.FASTGPT_PASSWORD_SHA256 });
const BASE = cfg.baseUrl.replace(/\/+$/, '');

async function fgFetch(path, { method = 'GET', body } = {}) {
  const token = await session.getToken();
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { Cookie: `fastgpt_token=${token}`, 'fastgpt-web-request': '1', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {})
  });
  const text = await res.text();
  let parsed;
  try { parsed = JSON.parse(text); } catch { parsed = text; }
  if (!res.ok) throw new Error(`HTTP ${res.status} ${method} ${path}: ${JSON.stringify(parsed).slice(0, 300)}`);
  return parsed && parsed.data !== undefined ? parsed.data : parsed;
}

const args = process.argv.slice(2);
const getArg = (name) => {
  const index = args.indexOf(`--${name}`);
  return index >= 0 ? args[index + 1] : undefined;
};
const datasetId = getArg('dataset');
const folderName = getArg('folder');
const files = args.reduce((acc, value, index) => (value === '--file' ? [...acc, args[index + 1]] : acc), []);
if (!datasetId || !folderName || files.length === 0) {
  console.error('用法：node tools/upload_delivery.mjs --dataset <id> --folder "<名称>" --file "<本地路径>::<库内文件名>"');
  process.exit(1);
}

const folder = await fgFetch('/api/core/dataset/collection/create', { method: 'POST', body: { datasetId, name: folderName, type: 'folder' } });
const folderId = typeof folder === 'string' ? folder : (folder.collectionId || folder._id || folder.id);
console.log('folder:', folderName, folderId);

for (const spec of files) {
  const [localPath, name = basename(spec)] = spec.split('::');
  const content = readFileSync(localPath);
  const presign = await fgFetch('/api/core/dataset/file/presignDatasetFilePostUrl', {
    method: 'POST',
    body: { datasetId, filename: name, size: content.byteLength },
  });
  const put = await fetch(presign.url, {
    method: 'PUT',
    headers: { 'content-type': presign.headers?.['content-type'] || 'application/octet-stream' },
    body: content,
  });
  if (put.status >= 300) throw new Error(`upload failed: HTTP ${put.status}`);
  const created = await fgFetch('/api/core/dataset/collection/create/fileId', {
    method: 'POST',
    body: { datasetId, fileId: presign.key, parentId: folderId, trainingType: 'backup', customPdfParse: false },
  });
  const collectionId = typeof created === 'string' ? created : (created.collectionId || created._id);
  console.log(JSON.stringify({
    collectionId,
    name,
    bytes: content.byteLength,
    entryLink: `${BASE}/dataset/detail?datasetId=${datasetId}&currentTab=dataCard&collectionId=${collectionId}`,
  }));
}
