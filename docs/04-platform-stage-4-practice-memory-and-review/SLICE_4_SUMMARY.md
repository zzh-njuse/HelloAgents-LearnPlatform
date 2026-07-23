# Stage 4 Slice 4 完成总结

状态：已于 2026-07-23 完成实现、真实环境接入、人工主路径 smoke、独立 OCR 与修复；Stage 4 因新增 Slice 5 稳定性收尾而尚未整体关闭。

## 实际完成

- 建立产品审核制 MCP capability：自托管代码执行与远程 Wolfram 科学工具。
- 代码执行通过独立 Ubuntu VM 中的 Judge0 运行，支持 Python、Java、C++，默认禁止执行网络访问，并仅向 Windows 宿主开放执行 API。
- 产品 worker 只通过固定 MCP `run_code` Tool 调用执行服务，不直接依赖 Judge0 HTTP；协议、服务器、Tool 和 canonical schema hash 均在调用前验证。
- Wolfram 采用固定远程 MCP 地址和 Tool allowlist，按 Job/Turn 授权与预算执行；失败降级且不伪造科学结论。
- 课程正文、练习和 Tutor 支持本地 KaTeX/`mhchem` 公式渲染；编程界面提供代码编辑、输入、运行结果和专注模式。
- Lesson、Practice 和 Tutor 已建立受控工具授权、trace、删除、取消、晚到结果及学习事实隔离边界。
- 代码和科学 Tool observation 只能作为当前 artifact/评分/讲解证据，不自动成为掌握度、Memory 或其他学习事实。
- capability probe 将真实握手结果写入有 TTL 的脱敏投影；API 不持有执行后端或 Wolfram 私密配置。

## 环境与真实验证

- Ubuntu VM：4 vCPU、受限网络、38 GB 根卷。
- Judge0 1.13.1：Python、Java、C++ 实际提交均成功；CPU、wall time、内存、文件大小、运行次数和网络权限均设置上限。
- Wolfram MCP：真实产品调用成功，并能返回科学计算结果。
- Compose 镜像、migration head、API `/ready`、Web HTTP 200、Web lint/build 和 MCP focused tests 已通过。
- Slice 4 最终 OCR 共 25 个分块；采纳的 High/高置信 Medium 已修复，正式记录见 [2026-07-23 Slice 4 OCR](reviews/2026-07-23-slice-4-ocr.md)。

## 已知限制与暂缓风险

- Java/C++ 编程练习和部分科学练习的**生成成功率与 artifact 合同稳定性仍不足**。真实执行 MCP 已可用，但生成 provider 可能产出无法通过结构、引用或 reference validation 的题目。
- 练习生成失败对用户的原因投影仍不够细，容易把“不适合该题型”“provider artifact 无效”“reference 执行失败”和“基础设施不可用”混为泛化失败。
- 练习去重目前不足以系统性避免与历史练习语义重复。
- API 全量 pytest 在本次 OCR 收尾的 120 秒和 300 秒命令窗口内未完成，因此不能记为通过；focused MCP/API 回归已通过。
- 破坏性删除人工 smoke 仍按既定决策留到 Stage 4 最终 Gate 一次完成。

## 为什么增加 Slice 5

原四切片计划把 MCP 能力接入和编程/科学练习的产品可用性放在同一 Slice。真实 smoke 证明：MCP 基础设施和授权边界已经成立，但上游课程画像、练习 artifact、reference validation、确定性评分与错误投影仍需要一次独立的端到端稳定性工作。继续把这些问题塞入 Slice 4 会让 MCP Gate 无限扩张，也不利于判断错误究竟来自生成、验证还是工具执行。

因此 Stage 4 增加计划外 Slice 5，只做练习生成与评分链路稳定化及 Stage 4 最终交付，不新增产品能力。

## 下一切片输入

见 [Slice 5 输入](SLICE_5_INPUTS.md)。Slice 5 必须先复核并接受新的 Spec；若改变 artifact/schema、重试预算、评分权威或队列状态，需要同步新增或修订 ADR。未经 Gate 不开始主体实现。
