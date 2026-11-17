---
name: pdf-merge-pipeline
description: 在 agent 沙箱里把本轮上传的多个文件（图片 / PDF / Word / Excel / PPT）逐个转成 PDF（页面大小与原文件一致，不缩放、不拉伸、不套 A4），按上传顺序合并成一个 PDF，再上传到 FastGPT 存储换可长期访问的下载链接。当任务要把多个文件合并成一个 PDF 时使用，本技能自带全部脚本，不需要任何外部常驻服务。
---

# 多文件转 PDF 并按上传顺序合并（保持原页面大小）

本技能目录自带转换、合并、上传、校验四步脚本，**在 agent 沙箱里就能跑完，不需要任何外部常驻服务**。

## 沙箱路径

技能目录在 `/workspace/projects/<版本号>/skills/pdf-merge-pipeline/`，用 `find /workspace -name SKILL.md` 定位，
不要凭记忆写路径。本轮上传的文件在 `<沙箱工作目录>/user_files/`，工作目录会写在「背景信息」里。

## 目录结构

```
scripts/
  convert_to_pdf.py    步骤 1：逐个转 PDF（保持页面大小），产出 convert_manifest.json
  merge_pdfs.py        步骤 2：按上传顺序合并，产出 merged.pdf 与 merged_report.json
  merge_to_pdf.py      入口：一次跑完步骤 1 + 步骤 2（与既有命令兼容）
  upload_result.py     步骤 3：上传合并结果到 FastGPT 存储，返回长期下载链接
  verify_result.py     步骤 4：校验产物与链接，产出最终报告 merged_result.json
  rules.py             公共模块：加载 config/page_rules.json（扁平引用，无多层嵌套）
config/
  page_rules.json      页面尺寸换算规则 / 文件类型白名单 / 失败原因文案（改这里即生效）
  pipeline.env         FASTGPT_BASE_URL / FASTGPT_API_TOKEN（用 set -a; . ./config/pipeline.env; set +a 载入）
```

## 怎么跑（固定四步，不要临场发挥）

### ① 写有序文件清单 `files.json`

用户的上传文件列表在对话上下文里，**顺序就是上传顺序**。把每个文件按顺序写进 `files.json`：

```json
["会议纪要.png", "文献综述.pdf", "汇报材料.docx"]
```

条目也可以写成对象 `{"name": "会议纪要.png"}`；如果上下文里给了绝对路径，就写 `{"name": "...", "path": "/abs/path"}`。
**顺序必须和上下文里的列表一致** —— 合并结果的页序 = 上传顺序 × 文件内页序。

### ② 转换并合并

```bash
cd /workspace/projects/<版本号>/skills/pdf-merge-pipeline
python3 scripts/merge_to_pdf.py --input-list files.json --out merged.pdf --report merged_report.json
```

脚本会自己按需 `pip install --break-system-packages pypdf pillow img2pdf`，不用你手动装。
最后一行输出是一段 JSON 报告：`ok`、`total_pages`、`merged_page_sizes`（每页宽高，单位 pt）、
`files`（每个文件的 `name`/`status`/`pages`/`page_sizes_pt`/`error`）。

### ③ 上传拿下载链接

```bash
cd /workspace/projects/<版本号>/skills/pdf-merge-pipeline
set -a; . ./config/pipeline.env; set +a
python3 scripts/upload_result.py merged.pdf --filename 合并结果.pdf
```

最后一行输出是一段 JSON：`download_link`、`filename`、`size`、`verified`。
**`download_link` 才是给用户的交付链接**；不要把 API Key、预签名上传地址、脚本日志贴给用户。

### ④ 校验并出最终报告

```bash
cd /workspace/projects/<版本号>/skills/pdf-merge-pipeline
python3 scripts/verify_result.py --report merged_report.json --upload upload_result.json --merged merged.pdf --out merged_result.json
```

校验合并产物页数与逐页宽高、交付链接形态（长期链接而非 2 小时预览链接）、链接可打开且类型为 PDF、
失败文件是否点名原因。最后一行输出最终报告 JSON（`files` / `total_pages` / `merged_page_sizes` / `download_link` / `checks`）。
**汇报用的页数与宽高一律取自这份报告里的数字。**

## 页面大小口径（核心）

| 源文件类型 | 处理方式 | 页面大小结果 |
|---|---|---|
| PDF | 直接沿用原页面 | 与原 PDF 页面尺寸、方向完全一致 |
| 图片（png/jpg 等） | 以图片自身尺寸生成单页，**1 px = 0.75 pt**（96 dpi 折算），不缩放、不裁剪、不加白边 | 页面尺寸 = 图片像素宽高 × 0.75 pt |
| Word / Excel / PPT | 用 headless LibreOffice 按文档自身页面设置转换，保留纸张方向 | 与原文档页面设置一致 |
| 其他类型 | 视为转换失败 | 该文件被跳过并在报告里写明原因 |

合并结果只有一个 PDF，页序 = 上传顺序 × 文件内页序，总页数 = 各文件页数之和。
以上换算规则、白名单与失败原因文案都在 `config/page_rules.json` 里，**改配置即生效，不用改代码**。

## 失败容错

单个文件转换失败（例如文件损坏、类型不支持、沙箱里没有 LibreOffice）时，脚本**不会中断**：
该文件记为 `status: failed` 并带上原因，其余文件照常转换并合并。
汇报时要点名失败的文件名与原因，并说明合并结果里包含哪些文件。

## 硬性约束

- 复杂逻辑写在脚本里，**不要拼超长命令**；单条命令控制在 200 字符以内，不要嵌套多层引号与子 shell，也不要用 `&&` 串联。
- 沙箱单条命令上限 **600 秒**；转换通常几十秒完成，不要 `tail -f`、不要 `while true`，需要等就用有界轮询。
- 不要在回复或日志里输出 `FASTGPT_API_TOKEN`、`config/pipeline.env` 的内容或预签名上传地址。
- 交付链接必须是第 ③ 步的 `download_link`；沙箱内置的 `Get File URL` 只是 2 小时过期的预览链接，不能当交付物。

## 出问题怎么判断

| 现象 | 原因 | 处理 |
|---|---|---|
| 报告里 `files` 为空 | `files.json` 写成了空数组或路径不对 | 先 `ls user_files/` 看真实文件名，再重写清单 |
| 某个文件 `error` 含 `找不到文件` | 清单里的名字与沙箱里的实际文件名不一致 | 用 `ls user_files/` 的真实文件名重写该条目 |
| 某个文件 `error` 含 `没有 LibreOffice` | 沙箱镜像没有 Office 渲染引擎 | 见下节「装 LibreOffice」，装完重跑第 ② 步 |
| `pip install` 被拦 | PEP 668 | 脚本已带 `--break-system-packages`，若仍失败用 `pip install --break-system-packages --user` 兜底 |
| 上传失败 `预签名失败` | API Key 失效 | 检查 `config/pipeline.env` 里的 `FASTGPT_API_TOKEN` 是否还在 |
| 合并结果页数不对 | 清单顺序与实际上传顺序不一致 | 回到上下文里的「对话文件」列表逐项核对顺序后重跑 |
| 图片页宽高与「像素 × 0.75」不符 | `config/page_rules.json` 的 `image.px_to_pt` 被改过 | 确认 `image.px_to_pt = 0.75`、`image.dpi = 96` |

## 装 LibreOffice（仅当沙箱里没有 soffice 时）

沙箱镜像常常不带 Office 渲染引擎。先确认：

```bash
which soffice
```

没有就按镜像的包管理器分步安装（**每条命令单独执行，不要用 `&&` 串联**）：

```bash
cat /etc/os-release
```

Alpine 系：

```bash
apk add --no-cache libreoffice
```

Debian 系：

```bash
apt-get update
```

```bash
apt-get install -y --no-install-recommends libreoffice
```

装完再执行一次 `which soffice` 确认，然后重跑第 ② 步。装不上就按「转换失败并说明原因」处理，其余文件照常合并。
