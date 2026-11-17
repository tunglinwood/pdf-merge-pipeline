# pdf-merge-pipeline（FastGPT 技能包源码）

FastGPT 工作流「多文件上传自动合并PDF（保持原页面大小）」的执行技能源码。
需求编号 **REQ-20261117-003 需求线 B**（multica 工单 TEAM-83）。

- 工作流 appId：`6afbb78fd3ccf4253b34830a`（门户 https://x.huamedicine.com/chat?appId=6afbb78fd3ccf4253b34830a ）
- 平台技能 skillId：`6afc6cd5d3ccf4253b38a81d`（`pdf-merge-pipeline`，v1.2；旧 `6afc239ed3ccf4253b37a9ec` 已随 v1.4 发布版删除）
- 端到端实测报告：[docs/实测报告-REQ-20261117-003-B线.md](docs/实测报告-REQ-20261117-003-B线.md)

## 技能做什么

把一个对话回合里上传的多个文件（图片 / PDF / Word / Excel / PPT）逐个转成 PDF，
**页面大小与原文件一致**，按上传顺序合并成一个 PDF，上传到平台存储换长期下载链接。

| 源文件类型 | 处理方式 | 页面大小结果 |
| --- | --- | --- |
| PDF | 原样沿用每一页 | 与源 PDF 页面尺寸、方向完全一致 |
| 图片 | 单页，**1 px = 0.75 pt**（96 dpi 折算），不缩放、不裁剪、不加白边 | 页面尺寸 = 像素宽高 × 0.75 pt |
| Word / Excel / PPT | headless LibreOffice 按文档自身页面设置转换 | 与原文档页面设置一致，方向保留 |
| 其他类型 | 视为转换失败 | 该文件被跳过并写明原因 |

合并结果只有一个 PDF，**页序 = 上传顺序 × 文件内页序**，总页数 = 各文件页数之和。

## 目录结构

```
skills/pdf-merge-pipeline/
  SKILL.md                     技能说明（agent 在沙箱里照着执行）
  scripts/rules.py             公共模块：加载配置（扁平引用，无多层嵌套）
  scripts/convert_to_pdf.py    步骤 1：逐个转 PDF → convert_manifest.json
  scripts/merge_pdfs.py        步骤 2：按上传顺序合并 → merged.pdf / merged_report.json
  scripts/merge_to_pdf.py      入口：步骤 1 + 步骤 2（与既有命令兼容）
  scripts/upload_result.py     步骤 3：上传到平台存储 → upload_result.json
  scripts/verify_result.py     步骤 4：校验产物与链接 → merged_result.json
  config/page_rules.json       页面尺寸换算规则 / 文件类型白名单 / 失败原因文案（可编辑）
  config/pipeline.env.example  凭据样例（真实 pipeline.env 不入库）
tools/
  make_samples.py              生成实测样例文件
  build_skill_zip.py           把技能目录打成平台可导入的 zip（结构 skills/<技能名>/...）
  run_app_test.mjs             上传样例并跑真实工作流链路
tests/
  test_stem_collision.py       回归测试：同名不同后缀的文件不得互相覆盖、页序必须一致
```

## 打包与导入（技能内容改动必须「删旧重导」）

平台侧只有 `update` 接口能改元数据，改内容不生效，所以改完内容按下面走：

```bash
python3 tools/build_skill_zip.py --source skills/pdf-merge-pipeline \
    --env /path/to/pipeline.env --out pdf-merge-pipeline.zip
```

平台导入时包内路径须为 `skills/pdf-merge-pipeline/...`（脚本已按此结构打包）。
导入顺序：**先删旧技能 → 再导入新包 → 把工作流 agent 节点的 `skills` 指向新 skillId → 发布 → `runtime/init`**。

## 本地自测

```bash
python3 tools/make_samples.py samples
python3 tests/test_stem_collision.py          # 同名不同后缀的回归测试（真实脚本跑）
cd skills/pdf-merge-pipeline
python3 scripts/merge_to_pdf.py --input-list ../../samples/files.json --out /tmp/merged.pdf --user-dir ../../samples
```

> `config/pipeline.env` 里放 `FASTGPT_BASE_URL` 与 `FASTGPT_API_TOKEN`（从环境变量或密钥配置读取，不入库、不写进代码与日志）。
