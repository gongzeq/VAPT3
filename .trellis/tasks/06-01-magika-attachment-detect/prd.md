# brainstorm: Magika 附件类型识别与 rspamd 附件传入

## Goal

引入 Google Magika AI 框架，在钓鱼邮件检测工作流中对附件进行真实文件类型识别，检测扩展名欺骗类攻击（如 .exe 伪装 .pdf）；同时解决 rspamd 如何将附件原始字节传入工作流，以及大附件截断策略的问题。

## What I already know

* 当前钓鱼邮件检测工作流为 3-step：step1(script 特征提取) → step2(LLM 判定) → step3(聚合回写)
* 当前 WorkflowInput 只有 6 个字段：sender / subject / body / urls / recipient / rspamd_score——**不含附件**
* rspamd Lua API 提供 `task:get_parts()` 可获取所有 MIME 部件，`task:get_text_parts()` 获取文本部件
* 每个 mime part 有 `get_filename()`、`get_content()`、`get_detected_type()` 等方法
* rspamd 已有 `rspamd_util` 模块可用于 base64 编码
* ScriptExecutor 有 60s 超时上限，step1/step3 必须控制在内
* ExecTool 有 `_MAX_OUTPUT` (100KB)，stdin JSON 不能过大
* 当前已有 `_content_hash` 去重逻辑（基于 sender + subject + body），附件不参与 hash
* 当前 `extract_urls()` 已从 `task:get_urls()` 提取链接
* 工作流模板使用 `${inputs.xxx}` 和 `${steps.stepN.result.parsed.xxx}` 插值语法
* step2 condition 禁止函数调用（`eval_bool` 不允 `float(inputs.x)`），需用上游 parsed 字段

## Research References

* [`research/magika-executable.md`](research/magika-executable.md) — Magika 可执行文件检测能力深度研究
  - 支持 216 种内容类型，含 pebin/elf/macho + js/ps1/vba/bat/shell 等 12+ 脚本类型
  - **截断结论：前 512 字节足以检测 PE/ELF/Mach-O，前 4096 字节覆盖所有格式的安全选择**
  - 模型 ~1MB，推理 ~5ms/文件，`HIGH_CONFIDENCE` 模式适合安全场景
  - ⚠️ 对抗攻击风险：修改 13 字节可绕过检测，需多源交叉验证

## Answers to Key Questions

### Q1: 大附件截断阈值？
**答：4096 字节。** 理由：
- PE/ELF/Mach-O 头结构 ≤ 512 字节即足够
- 脚本文件（.js/.ps1）特征分散在全文，前 4096 字节可覆盖头部特征 + 初始代码
- Office 文档（.docx/.xlsx）的 ZIP 局部文件头在前 512 字节内
- 4096 bytes → base64 ≈ 5462 chars，5 个附件总共约 27KB——远低于 limits

### Q2: 附件 base64 编码后 WorkflowInput 大小？
**答：安全上限远高于需求。** 计算：
- 单附件：4096 raw → 5462 base64 + JSON 元数据 ≈ 6KB
- 5 附件上限：5 × 6KB ≈ 30KB（attachments 字段总大小）
- 整个 POST JSON（含其他 6 个字段）< 50KB——远低于 HTTP body 典型限制

### Q3: 附件数量上限？
**答：5 个。** 理由：
- 典型钓鱼邮件罕有超过 5 个附件
- 30KB 总量远低于任何瓶颈（POST body / stdin / stdout）

### Q4: content_hash 是否需要纳入附件？
**答：是，采用全量刷新方案。** 
- 直接修改 `_content_hash()` 算法，纳入附件特征（文件名 + Magika 真实类型 label）
- 已有缓存条目自然过期（TTL 7 天），无需迁移逻辑
- 附件不同的相似邮件不会被错误缓存命中

## Assumptions (validated)

* ✅ rspamd `rspamd_util` 模块支持 base64 编码（Lua 标准模式）
* ✅ Magika ONNX 推理可在 Python 3.12 环境运行（纯 Python + onnxruntime）
* ✅ 首期只做类型识别（Magika label + extension_mismatch），不解析附件文本内容
* ✅ 附件分析结果通过 step1 features 输出给 step2 LLM

## Decision (ADR-lite)

**Context**: content_hash 缓存策略 + 宏文件可疑度评分

**Decision 1 — content_hash 全量刷新**: 直接修改 `_content_hash()` 纳入附件文件名 + Magika label，不保留向后兼容。已有缓存 TTL 7 天自然过期。

**Decision 2 — 宏文件自动加 suspicious_score**: step1 检测附件是否为宏能力文件（旧格式 .doc/.xls/.ppt 或显式宏文件 .docm/.xlsm/.pptm），step3 在看到 `has_macro_capable=true` 时自动给 `add_score` 加固定阈值（+2.0/附件），同时 LLM 也将该信号纳入判定。

**Consequences**: 
- 缓存全量刷新：7 天内重复邮件会多走一轮 LLM，影响可控
- 宏文件评分加成：即使 LLM 对正文判定为低风险，宏文件附件也会推高最终 rspamd score

## Requirements

### 核心：附件提取与传输
* [ ] R1: rspamd Lua 插件从 `task:get_parts()` 提取非文本附件（跳过 text/plain、text/html）
* [ ] R2: 附件原始字节截断至前 4096 字节，base64 编码后传入 `attachments` WorkflowInput
* [ ] R3: 附件数量上限 5 个，单附件截断 4096 字节（base64 后 ≈ 5.5KB）
* [ ] R4: 无附件邮件 `attachments=[]`，向后兼容

### 核心：Magika 类型识别
* [ ] R5: step1 集成 Magika（`HIGH_CONFIDENCE` 模式），对每个附件做 `identify_bytes()`
* [ ] R6: 检测扩展名欺骗 — `declared_extension` vs `magika_label` 不一致 → `extension_mismatch=true`
* [ ] R7: 检测宏能力文件 — 旧格式(doc/xls/ppt) 或显式宏文件(docm/xlsm/pptm) → `is_macro_capable=true`
* [ ] R8: Magika 加载失败降级 — 仅上报文件名/声明类型，`magika_error` 字段标记

### 核心：评分与判定
* [ ] R9: step3 对 `is_macro_capable=true` 的附件自动加 `add_score += 2.0`（每文件）
* [ ] R10: step2 LLM prompt 纳入附件分析结果（类型、是否不匹配、是否宏文件）
* [ ] R11: content_hash 全量刷新 — 纳入附件文件名 + Magika label 排序后的 hash

### 核心：数据持久化
* [ ] R12: step3 SQLite `detection_results` 表新增 `attachments_json` 列，存储附件分析结果
* [ ] R13: step3 `risk_factors` 数组追加附件相关风险因子

## Acceptance Criteria

* [ ] AC1: 含 .exe 伪装 .pdf 的钓鱼邮件 → Magika 检测到 `extension_mismatch` → LLM 判定钓鱼 → rspamd 加分
* [ ] AC2: 含 .docm 宏文件的邮件 → `is_macro_capable=true` → add_score 自动 +2.0
* [ ] AC3: 同一邮件两次投递（附件相同）→ 第二次命中缓存，step2 skip
* [ ] AC4: 同一邮件换附件再投递 → 新 content_hash，不命中旧缓存
* [ ] AC5: 5 个附件 × 4096 bytes → POST body < 50KB → 无超限
* [ ] AC6: 无附件邮件 → `attachments=[]` → 行为与变更前完全一致
* [ ] AC7: Magika 未安装时 → 降级输出 `magika_error="not_installed"` → 邮件正常放行

## Definition of Done (team quality bar)

* 改动文件：ai_phishing.lua / templates.py / scripts.py
* 新增依赖：magika（pip install）
* 部署脚本更新（如需要）
* 端到端测试：发一封带伪装附件的邮件验证链路

## Macro-Capable File Detection — 详细规则

触发 `is_macro_capable=true` 的条件（任一满足）：

| 场景 | Magika label | 文件扩展名 | 触发原因 |
|------|-------------|-----------|----------|
| 旧格式文档 | `doc` | .doc | CDF 格式原生支持宏 |
| 旧格式表格 | `xls` | .xls | CDF 格式原生支持宏 |
| 旧格式演示 | `ppt` | .ppt | CDF 格式原生支持宏 |
| 显式宏文档 | `docx` | .docm | OOXML 宏启用变体 |
| 显式宏表格 | `xlsx` | .xlsm | OOXML 宏启用变体 |
| 显式宏演示 | `pptx` | .pptm | OOXML 宏启用变体 |
| 模板文件 | `doc`/`docx` | .dot/.dotm | 模板可含宏 |

`add_score` 宏加成公式（step3）：
```
add_score = confidence × 8.0 + (macro_capable_count × 2.0)
```
- 单个宏文件：LLM 判 0.3 → 0.3×8.0 + 2.0 = 4.4（接近 greylist 阈值 4）
- 两个宏文件：LLM 判 0.3 → 0.3×8.0 + 4.0 = 6.4（触发 add_header）

## Out of Scope (explicit)

* 附件文本内容深度解析（如 PDF 文本提取、Office 文档解析）→ 后续
* 链接目标页面抓取 → 后续
* SPF/DKIM/DMARC 独立信号进 condition → PRD 已有 out of scope
* Magika CLI 模式 → 只使用 Python API
* Office 文档内部 VBA 宏代码提取与检测 → 后续（需解压 ZIP 分析 vbaProject.bin）
* 加密附件（ZIP/RAR 带密码）特殊处理 → 后续

## Technical Notes

* 关键文件：
  - `/home/administrator/VAPT3/.trellis/tasks/05-13-phishing-email-workflow/ai_phishing.lua` — Lua 插件
  - `/home/administrator/VAPT3/secbot/workflow/templates.py` — 工作流模板
  - `/home/administrator/VAPT3/secbot/workflow/scripts.py` — step1/step3 Python 脚本
* 约束：
  - ScriptExecutor 60s 超时
  - ExecTool `_MAX_OUTPUT` 100KB
  - rspamd POST body 超时 120s
  - step2 condition 禁止函数调用
  - WorkflowInput type 支持 string/file/boolean/number
