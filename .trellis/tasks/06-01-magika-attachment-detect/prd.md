# brainstorm: Magika 附件类型识别与 rspamd 附件传入

## Goal

引入 Google Magika AI 框架，在钓鱼邮件检测工作流中对附件进行真实文件类型识别，检测扩展名欺骗类攻击（如 .exe 伪装 .pdf）；同时解决 rspamd 如何将附件原始字节传入工作流，以及大附件截断策略的问题。

## What I already know

* 当前钓鱼邮件检测工作流为 3-step：step1(script 特征提取) → step2(LLM 判定) → step3(聚合回写)
* 当前 WorkflowInput 只有 6 个字段：sender / subject / body / urls / recipient / rspamd_score——**不含附件**
* rspamd Lua API（官方文档确认）：
  - `task:get_parts()` → 返回 `rspamd_mime_part` 列表（所有 MIME 部件）
  - `mime_part:is_attachment()` → 是否是附件；`mime_part:is_text()` → 是否文本；`mime_part:is_multipart()` → 是否多部分
  - `mime_part:get_filename()` → 文件名；`mime_part:get_type()` → content-type；`mime_part:get_detected_type()` → rspamd 检测类型
  - `mime_part:get_content()` → **MIME 解码后**的实际文件字节（base64/QP 已解码）— Magika 分析用这个
  - `mime_part:get_raw_content()` → MIME 编码后的原始内容（未解码）— 不用
  - `mime_part:get_length()` → 内容字节数
* `rspamd_util.encode_base64(input, 0)` — base64 编码，第二参数 `str_len=0` 表示不换行；input 接受 text 或 string
* ScriptExecutor 有 60s 超时上限，step1/step3 必须控制在内
* ExecTool 有 `_MAX_OUTPUT` (100KB)，stdin JSON 不能过大
* 当前已有 `_content_hash` 去重逻辑（基于 sender + subject + body），附件不参与 hash
* 当前 `extract_urls()` 已从 `task:get_urls()` 提取链接
* 工作流模板使用 `${inputs.xxx}` 和 `${steps.stepN.result.parsed.xxx}` 插值语法
* step2 condition 禁止函数调用（`eval_bool` 不允 `float(inputs.x)`），需用上游 parsed 字段

## Research References

* [Magika 论文 (arXiv:2409.13768)](https://arxiv.org/html/2409.13768v1) — ICSE 2025
  - 支持 200+ 种内容类型，含 pebin/elf/macho + js/ps1/vba/bat/shell 等 12+ 脚本类型
  - 模型 ~3MB（standard_v3_3），推理 ~5ms/文件，`HIGH_CONFIDENCE` 模式适合安全场景
  - ⚠️ 对抗攻击风险：修改 13 字节可绕过检测，需多源交叉验证
* **Magika standard_v3_3 采样策略（源码确认）**：
  - 模型输入 = beg 1024B + end 1024B = 2048B（`mid_size=0`，不再使用中间段）
  - 提取方式：从文件头读 block_size(4096)B → lstrip → 取前 beg_size(1024)B；从文件尾读 block_size(4096)B → rstrip → 取后 end_size(1024)B
  - **截断结论：必须同时提取文件头和文件尾，仅取头部会丢失文件尾部关键特征**
  - 参见 [config.min.json](https://github.com/google/magika/blob/main/python/src/magika/models/standard_v3_3/config.min.json) 和 [magika.py `_extract_features_from_seekable`](https://github.com/google/magika/blob/main/python/src/magika/magika.py)

## Answers to Key Questions

### Q1: 大附件截断阈值？
**答：head 4096B + tail 4096B = 8192B（两段拼接）。** 理由：
- Magika standard_v3_3 模型输入 = beg_size(1024) + end_size(1024) = 2048B，从 head/tail 各读 block_size(4096)B 后 strip 空白再提取
- 仅取前 4096B 会导致 Magika 的 end 段从第 3584 字节附近采样，**文件尾部特征完全丢失**
- head 4096B 覆盖 PE/ELF/Mach-O 头结构、ZIP 局部文件头、脚本头部声明
- tail 4096B 覆盖 ZIP end-of-central-directory、PE 节区表尾部、脚本尾部特征
- 小文件（≤ 8192B）：直接传完整内容，head/tail 自然重叠不影响
- 大文件（> 8192B）：Lua 提取 head 4096B + tail 4096B 拼接为 8192B 传给 `identify_bytes()`
- 8192 bytes → base64 ≈ 10924 chars，5 个附件总共约 55KB——仍在 limits 内

### Q2: 附件 base64 编码后 WorkflowInput 大小？
**答：可接受，但需注意 stdin 体积。** 计算：
- 单附件：8192 raw → 10924 base64 + JSON 元数据 ≈ 11KB
- 5 附件上限：5 × 11KB ≈ 55KB（attachments 字段总大小）
- 整个 POST JSON（含其他 6 个字段）≈ 60-70KB——低于 HTTP body 限制
- ⚠️ ExecTool `_MAX_OUTPUT` 为 100KB，stdin JSON 含附件 base64 后需控制在此范围内

### Q3: 附件数量上限？
**答：5 个。** 理由：
- 典型钓鱼邮件罕有超过 5 个附件
- 55KB 总量在可接受范围内（POST body / stdin / stdout 均未超限）

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
* [ ] R1: rspamd Lua 插件从 `task:get_parts()` 遍历 MIME parts，筛选附件：
  - 跳过 `is_text()==true` 的部件（text/plain、text/html 正文）
  - 跳过 `is_multipart()==true` 的容器部件
  - 保留 `is_attachment()==true` 或有 `get_filename()` 的部件
  - 上限 5 个附件
* [ ] R2: 每个附件用 `get_content()` 获取 MIME 解码后字节，按 head+tail 策略截断：
  - `get_length() <= 8192` → 完整内容直接 base64 编码
  - `get_length() > 8192` → 取前 4096B + 后 4096B 拼接为 8192B，再 base64 编码
  - `rspamd_util.encode_base64(sample, 0)` 编码（不换行）
  - 附件 JSON 结构：`{filename, content_type, content_base64, original_size}`
* [ ] R3: 附件数量上限 5 个，单附件截断 8192 字节（base64 后 ≈ 11KB）
* [ ] R4: 无附件邮件 `attachments="[]"`（JSON 字符串，type=string），向后兼容

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
* [ ] AC5: 5 个附件 × 8192 bytes → POST body < 80KB → 无超限
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

## Lua 附件提取实现细节

```lua
-- 伪代码：在 call_ai_service(task) 中新增附件提取
local function extract_attachments(task)
    local parts = task:get_parts()
    if not parts then return '[]' end

    local attachments = {}
    for _, part in ipairs(parts) do
        if #attachments >= 5 then break end
        if part:is_multipart() or part:is_text() then
            -- 跳过 multipart 容器和 text 正文
            goto continue
        end

        local filename = part:get_filename()
        if not filename or filename == '' then
            goto continue
        end

        local content = tostring(part:get_content())  -- MIME 解码后字节
        local total_len = #content
        local sample
        if total_len <= 8192 then
            sample = content
        else
            -- head 4096B + tail 4096B 拼接
            sample = content:sub(1, 4096) .. content:sub(total_len - 4095)
        end

        local b64 = tostring(rspamd_util.encode_base64(sample, 0))
        table.insert(attachments, {
            filename = filename,
            content_type = part:get_type() or '',
            content_base64 = b64,
            original_size = total_len,
        })
        ::continue::
    end

    return ucl.to_format(attachments, 'json-compact')
end
```

**POST body 结构（新增 `attachments` 字段）：**
```json
{
  "inputs": {
    "sender": "...",
    "subject": "...",
    "body": "...",
    "urls": "[...]",
    "recipient": "...",
    "rspamd_score": "6.50",
    "attachments": "[{\"filename\":\"invoice.pdf\",\"content_type\":\"application/pdf\",\"content_base64\":\"JVBERi0...\",\"original_size\":1048576}]"
  }
}
```

**关键注意事项：**
- `attachments` 以 JSON 字符串传入（WorkflowInput type=string），与 `urls` 的 dual-shape 模式一致
- `get_content()` 返回 `rspamd_text`，需 `tostring()` 转为 Lua 字符串才能用 `:sub()` 截取
- `encode_base64(sample, 0)` 第二参数 `0` = 不换行，避免 JSON 转义问题
- `get_content()` 是 zero-copy 引用 rspamd 内部缓冲区，不会额外复制大文件到内存

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
