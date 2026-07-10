# Stage 0R Review 记录

文档规整本身使用 self-review、链接检查和 `git diff --check`，不运行付费 OCR。后续若 Stage 0R 出现依赖配置、测试修复或其他有意义代码 diff，再按以下模板记录 OCR。

## OCR 预检

```powershell
git status --short
git diff --stat
where.exe ocr
ocr version
ocr review --preview
```

准备运行真实 review 时：

```powershell
ocr llm test
ocr review --audience agent --background "Stage 0R dependency/test baseline or prototype contract work"
```

## Review 记录模板

```markdown
# Review：<topic>

日期：YYYY-MM-DD
阶段：Platform Stage 0R
审查范围：<diff/commit/ref>

## 背景

<业务目标、非目标、风险>

## 命令

<preview、real review、focused tests>

## 结果摘要

- High：
- Medium：
- Low：

## 采纳项

<finding、修复、理由>

## 暂缓或拒绝项

<finding、理由、后续 Stage>

## 复验

<命令与实际结果>
```

真实 OCR 需要用户要求或明确批准。finding 不自动决定修改；High 优先修复，Medium 结合上下文判断，Low 不盲改。
