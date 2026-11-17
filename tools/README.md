# 实测工具

## make_samples.py

生成与本次实测同规格的样例文件：

```bash
python3 tools/make_samples.py samples
```

| 文件 | 规格 | 期望页面尺寸 |
| --- | --- | --- |
| `会议纪要.png` | 1200×800 px | 900 × 600 pt（像素 × 0.75） |
| `文献综述.pdf` | 2 页：A4 纵向 + A5 横向 | 595.28 × 841.89 / 841.89 × 595.28 pt（原样沿用） |
| `汇报材料.docx` | A5 纵向页面设置 | 约 419.56 × 595.3 pt |
| `测试表格.xlsx` | A4 横向 | 841.89 × 595.3 pt（横向保留） |
| `测试幻灯片.pptx` | 16:9 | 959.98 × 540 pt |
| `损坏文件.docx` | 伪造 zip 头 | 转换失败（用于验证「点名原因 + 其余继续合并」） |

## run_app_test.mjs

上传样例并跑一次真实工作流链路（不是模拟）：

```bash
node tools/run_app_test.mjs <appId> <输出前缀> <文件1> <文件2> ...
```

前置条件：本机装有 `fastgpt-mcp`（提供 `FastGPTSession`）与 `~/.config/fastgpt-mcp/env` 里的平台会话配置；
脚本用 `node:https` 直连，不受 `fetch` 300 秒响应头超时限制（沙箱装 LibreOffice 时整轮可能跑 3~5 分钟）。

产出：`<前缀>_uploaded.json`（上传结果）、`<前缀>_result.json`（原始回复与耗时）、控制台里的应用回复原文。

## upload_delivery.mjs / verify_delivery.py（知识库交付）

把交付物落到 FastGPT 知识库的文件集合，并实测「需求方能打开、能下载」。

```bash
node tools/upload_delivery.mjs --dataset <datasetId> --folder "B线交付物（…）" \
  --file "/path/合并结果-case1.pdf::合并结果-case1-4页-混合上传-png-多页pdf-docx.pdf"

FASTGPT_TOKEN=<fastgpt_token> python3 tools/verify_delivery.py --manifest delivery_manifest.json
```

要点：

- 条目用 **`trainingType=backup`**（只存文件、不做向量训练）。默认 chunk 模式对「几乎无文本层」的合并 PDF
  会训练失败，条目在 `collection/read` / `collection/delete` 上返回 `501003 unExistCollection`（列表看得到、打不开）；
- 校验要**匿名 GET** 条目原文（不带登录态），确认需求方点开就能下载，而不是只在我自己的会话里能取到；
- 正式交付给需求方的是**知识库集合链接 + 条目 id**，不是 `/api/system/file/d/...` 临时直链（后者与发起会话绑定，
  需求方打开会得到 `HTTP 500 / 507003 unAuthFile`）。
