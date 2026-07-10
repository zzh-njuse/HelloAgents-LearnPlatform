# Review：Stage 2 切片与 Agent/OCR 规则修正

日期：2026-07-10

阶段：Platform Stage 0R

## 背景

本次文档修正恢复 Stage 2 的两个交付切片，新增根 `AGENTS.md`，并把已部署 OCR 的门禁流程写回 Playbook 和 Stage review 模板。

## 审查范围

- `AGENTS.md`
- `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- 文档索引和 Stage 0R review 入口

## 命令与结果

```powershell
where.exe ocr
ocr version
ocr review --preview
```

结果：

- `where.exe ocr` 未返回文件路径。
- `ocr version` 成功，版本为 `open-code-review dev windows/amd64`。
- `ocr review --preview` 成功识别 6 个变更文件。
- 6 个文件均为 Markdown，因 `unsupported_ext` 排除。

## 结论

没有运行付费真实 OCR review。Markdown 不在当前 OCR code review 有效范围内，因此本次使用人工/Codex self-review、相对链接检查和 `git diff --check` 完成验证。

## 复验

- Markdown 相对链接：`BROKEN=0`。
- `git diff --check`：通过。
- Stage 2 路线已明确切片 1 单文件管线、切片 2 批量上传与带引用答案。
