// 上传测试文件到 FastGPT 对话文件区，并用 /api/v1/chat/completions 跑一次真实链路。
// 用法: node run_test.mjs <appId> <outPrefix> <file1> <file2> ...
// 说明：对话可能跑好几分钟（沙箱里装 LibreOffice 等），所以用 node:https 直连，不受 fetch 300s 头超时限制。
import { readFileSync, writeFileSync } from 'node:fs';
import { basename, extname } from 'node:path';
import https from 'node:https';
import { FastGPTSession } from '/home/huasmex/workspace/fastgpt-mcp/dist/session.js';

const env = Object.fromEntries(
  readFileSync('/home/huasmex/.config/fastgpt-mcp/env', 'utf8')
    .split('\n')
    .filter((l) => l.includes('='))
    .map((l) => {
      const i = l.indexOf('=');
      return [l.slice(0, i).trim(), l.slice(i + 1).trim()];
    })
);
const cfg = JSON.parse(readFileSync('/home/huasmex/workspace/fastgpt-mcp/config/config.json', 'utf8'));
const session = new FastGPTSession({ ...cfg, passwordDigest: env.FASTGPT_PASSWORD_SHA256 });
const BASE = cfg.baseUrl.replace(/\/+$/, '');

const APP_ID = process.argv[2];
const OUT_PREFIX = process.argv[3];
const files = process.argv.slice(4);
const question = process.env.QUESTION || '请把本轮上传的文件逐个转成 PDF（保持原页面大小）并按上传顺序合并成一个 PDF。';

const chatId = `bline-${OUT_PREFIX}-${Date.now().toString(36)}`;
const token = await session.getToken();
const headers = { Cookie: `fastgpt_token=${token}`, 'fastgpt-web-request': '1', 'Content-Type': 'application/json' };

/** 用 node:https 发请求，不设超时。 */
function request(method, urlString, { body, reqHeaders = {}, timeoutMs = 0 } = {}) {
  const url = new URL(urlString);
  const payload = body === undefined ? undefined : (Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body)));
  const opts = {
    method,
    hostname: url.hostname,
    port: url.port || 443,
    path: url.pathname + url.search,
    headers: { ...reqHeaders, ...(payload ? { 'Content-Length': payload.byteLength } : {}) }
  };
  return new Promise((resolve, reject) => {
    const req = https.request(opts, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => resolve({
        status: res.statusCode,
        headers: res.headers,
        body: Buffer.concat(chunks)
      }));
    });
    req.on('error', reject);
    if (timeoutMs) req.setTimeout(timeoutMs, () => req.destroy(new Error('socket timeout')));
    if (payload) req.write(payload);
    req.end();
  });
}

const CONTENT_TYPES = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.pdf': 'application/pdf',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.doc': 'application/msword',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
};

const uploadOne = async (path) => {
  const filename = basename(path);
  const body = Buffer.from(readFileSync(path));
  const presignRes = await request('POST', `${BASE}/api/core/chat/file/presignChatFilePostUrl`, {
    body: {
      filename,
      contentType: CONTENT_TYPES[extname(filename).toLowerCase()],
      size: body.byteLength,
      appId: APP_ID,
      chatId
    },
    reqHeaders: headers
  });
  const presign = JSON.parse(presignRes.body.toString('utf8'));
  if (presign.code !== 200) throw new Error(`presign failed: ${JSON.stringify(presign).slice(0, 300)}`);
  const data = presign.data;
  const put = await request('PUT', data.url, {
    body,
    reqHeaders: { 'content-type': data.headers?.['content-type'] || 'application/octet-stream' }
  });
  if (put.status >= 300) throw new Error(`upload failed: ${put.status}`);
  console.log(`uploaded ${filename} -> ${data.previewUrl}`);
  return { name: filename, url: data.previewUrl, key: data.key };
};

const uploaded = [];
for (const f of files) uploaded.push(await uploadOne(f));
writeFileSync(`${OUT_PREFIX}_uploaded.json`, JSON.stringify(uploaded, null, 1));

const content = [
  { type: 'text', text: question },
  ...uploaded.map((f) => ({ type: 'file_url', name: f.name, url: f.url, fileType: 'file', key: f.key }))
];

const started = Date.now();
const runRes = await request('POST', `${BASE}/api/v1/chat/completions`, {
  body: {
    appId: APP_ID,
    chatId,
    messages: [{ role: 'user', content }],
    stream: false,
    detail: false,
    variables: {},
    responseChatItemId: '',
    retainDatasetCite: false,
    showSkillReferences: false
  },
  reqHeaders: headers
});
const seconds = Math.round((Date.now() - started) / 1000);
const text = runRes.body.toString('utf8');
let body;
try { body = JSON.parse(text); } catch { body = { raw: text }; }
writeFileSync(`${OUT_PREFIX}_result.json`, JSON.stringify({ http: runRes.status, seconds, chatId, body }, null, 1));
console.log('HTTP', runRes.status, 'elapsed_s', seconds, 'chatId', chatId);
const reply = body?.choices?.[0]?.message?.content ?? JSON.stringify(body).slice(0, 4000);
console.log('----- REPLY -----');
console.log(reply);
console.log('----- END -----');
