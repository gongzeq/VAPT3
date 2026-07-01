local rspamd_logger = require "rspamd_logger"
local rspamd_http = require "rspamd_http"
local rspamd_util = require "rspamd_util"
local ucl = require "ucl"

-- 配置：调用 secbot 钓鱼邮件检测工作流（替代下线的 ai_detector.py:5001）
-- 来源：.trellis/tasks/05-13-phishing-email-workflow/prd.md §R2
--
-- 2026-06-02 更新：
--   1. 移除评分区间过滤，所有邮件均进入 workflow
--   2. 修复 body 非 UTF-8 编码导致 gateway 400 错误的问题

local ai_config = {
    enabled = true,
    workflow_run_url = "http://127.0.0.1:18791/api/workflows/wf_7d5f9008/run",
    request_timeout = 130,
    internal_domains = { "gdmsa1.gov.cn" },
}

-- Magika label 对应的高风险文件类型
local _DANGEROUS_LABELS = {
    pebin = true, elf = true, macho = true,           -- 可执行文件
    javascript = true, powershell = true, vba = true, -- 脚本/宏
    batch = true, shell = true,                       -- 批处理/Shell
    lnk = true, iso = true,                           -- 快捷方式/镜像
    apk = true, jar = true, dex = true,              -- 移动/Java
    wasm = true,                                      -- WebAssembly
}

-- 检查内部域名
local function is_internal_domain(sender)
    if not sender or sender == "" then
        return false
    end
    local domain = string.match(sender, "@(.+)$")
    if not domain then
        return false
    end
    for _, d in ipairs(ai_config.internal_domains) do
        if string.lower(domain) == string.lower(d) then
            return true
        end
    end
    return false
end

-- 提取邮件URL（兼容 URL 对象和纯字符串两种格式）
local function extract_urls(task)
    local urls = {}
    local parts = task:get_urls()
    if parts then
        for _, u in ipairs(parts) do
            local url_str
            if type(u) == 'table' and u.get_text then
                url_str = u:get_text()
            else
                url_str = tostring(u)
            end
            if url_str and url_str ~= "" then
                table.insert(urls, url_str)
            end
        end
    end
    return urls
end

-- 提取邮件附件（非文本 MIME parts）
-- PRD: 06-01-magika-attachment-detect §R1 §R2
-- 截断策略：head 4096B + tail 4096B = 8192B（Magika standard_v3_3 采样要求）
local function extract_attachments(task)
    local parts = task:get_parts()
    if not parts then
        return '[]'
    end

    local attachments = {}
    for _, part in ipairs(parts) do
        if #attachments >= 5 then
            break
        end

        local part_filename = "unknown"
        local ok_skip = pcall(function()
            -- 跳过 multipart 容器和 text 正文
            if part.is_multipart and part:is_multipart() then return end
            if part.is_text and part:is_text() then return end

            local filename = part:get_filename()
            if not filename or filename == "" then
                return
            end
            part_filename = filename

            -- get_content() 返回 MIME 解码后的实际字节 (rspamd_text)
            local content_raw = part:get_content()
            if not content_raw then
                return
            end
            local content = tostring(content_raw)
            local total_len = #content
            if total_len == 0 then
                return
            end

            -- head + tail 截断策略
            local sample
            if total_len <= 8192 then
                sample = content
            else
                sample = content:sub(1, 4096) .. content:sub(total_len - 4095)
            end

            local b64 = tostring(rspamd_util.encode_base64(sample, 0))
            local content_type = ""
            if part.get_type then
                content_type = part:get_type() or ""
            end

            table.insert(attachments, {
                filename = filename,
                content_type = content_type,
                content_base64 = b64,
                original_size = total_len,
            })
        end)
        if not ok_skip then
            rspamd_logger.warnx(task, "附件提取失败，跳过该 part: %s", part_filename)
        end
    end

    return ucl.to_format(attachments, "json-compact")
end

-- 清理 body 中的非 UTF-8 字节，避免 gateway JSON 解码失败
local function sanitize_body(raw)
    if not raw then
        return ""
    end
    -- task:get_content() 返回 rspamd_text 对象，需要先转为 Lua string
    local s = tostring(raw)
    if s == "" then
        return ""
    end
    -- 移除 NUL 字节（C 字符串终止符）
    s = string.gsub(s, "%z", "")
    -- 限制长度（防止超大邮件体导致 JSON 过大）
    if #s > 50000 then
        s = string.sub(s, 1, 50000)
    end
    -- 替换无效 UTF-8 序列为空格（逐字节校验）
    local result = {}
    local i = 1
    local len = #s
    while i <= len do
        local b = string.byte(s, i)
        if b < 0x80 then
            table.insert(result, string.char(b))
            i = i + 1
        elseif b >= 0xC0 and b <= 0xDF then
            if i + 1 <= len then
                local b2 = string.byte(s, i+1)
                if b2 >= 0x80 and b2 <= 0xBF then
                    table.insert(result, string.sub(s, i, i+1))
                    i = i + 2
                else
                    table.insert(result, " ")
                    i = i + 1
                end
            else
                i = i + 1
            end
        elseif b >= 0xE0 and b <= 0xEF then
            if i + 2 <= len then
                local b2 = string.byte(s, i+1)
                local b3 = string.byte(s, i+2)
                if b2 >= 0x80 and b2 <= 0xBF and b3 >= 0x80 and b3 <= 0xBF then
                    table.insert(result, string.sub(s, i, i+2))
                    i = i + 3
                else
                    table.insert(result, " ")
                    i = i + 1
                end
            else
                i = i + 1
            end
        elseif b >= 0xF0 and b <= 0xF7 then
            if i + 3 <= len then
                local b2 = string.byte(s, i+1)
                local b3 = string.byte(s, i+2)
                local b4 = string.byte(s, i+3)
                if b2 >= 0x80 and b2 <= 0xBF and b3 >= 0x80 and b3 <= 0xBF and b4 >= 0x80 and b4 <= 0xBF then
                    table.insert(result, string.sub(s, i, i+3))
                    i = i + 4
                else
                    table.insert(result, " ")
                    i = i + 1
                end
            else
                i = i + 1
            end
        else
            table.insert(result, " ")
            i = i + 1
        end
    end
    return table.concat(result)
end

-- 安全解析 step3 stdout 的 JSON。secbot workflow run 响应结构：
--   { stepResults = { step3 = { output = { stdout = "<JSON 字符串>" } } } }
-- step3 的 stdout 契约（PRD §Technical Approach）：
--   { add_score, is_phishing, confidence, reason, suggested_action, risk_factors, attachments_json, ... }
local function parse_workflow_response(body)
    if not body or body == "" then
        return nil, "empty body"
    end
    local parser = ucl.parser()
    local ok, err = parser:parse_string(body)
    if not ok then
        return nil, "outer parse failed: " .. tostring(err)
    end
    local obj = parser:get_object()
    if type(obj) ~= "table" then
        return nil, "outer not table"
    end
    -- 工作流响应在 to_dict() 中已 camelCase
    local step_results = obj.stepResults or obj.step_results
    if type(step_results) ~= "table" then
        return nil, "missing stepResults"
    end
    local step3 = step_results.step3
    if type(step3) ~= "table" then
        return nil, "missing step3"
    end
    local output = step3.output
    if type(output) ~= "table" then
        return nil, "missing step3.output"
    end
    local stdout = output.stdout
    if type(stdout) ~= "string" and type(stdout) ~= "userdata" then
        return nil, "missing step3.output.stdout"
    end
    local stdout_str = tostring(stdout)
    if stdout_str == "" then
        return nil, "stdout is empty"
    end
    -- 使用 ucl 解析 stdout JSON，直接返回完整对象（参照 trellis 版本）
    local inner = ucl.parser()
    local ok2, err2 = inner:parse_string(stdout_str)
    if not ok2 then
        return nil, "stdout parse failed: " .. tostring(err2)
    end
    local result = inner:get_object()
    if type(result) ~= "table" then
        return nil, "stdout not object"
    end
    return result, nil
end

-- 从 attachments_json 构建附件风险警告（只检查附件自身的客观风险）
local function build_attachment_warning(attachments_json)
    local warnings = {}

    -- 只从 attachments_json 逐附件解析，检查附件自身的客观风险
    -- 不收集通用 risk_factors（如"非官方域名"等），避免正常附件被误标
    if attachments_json and attachments_json ~= "" and attachments_json ~= "[]" then
        local parser = ucl.parser()
        local ok = parser:parse_string(attachments_json)
        if ok then
            local attachments = parser:get_object()
            if type(attachments) == "table" then
                for _, att in ipairs(attachments) do
                    if type(att) == "table" then
                        local fname = tostring(att.filename or "unknown")
                        local label = tostring(att.magika_label or "unknown")
                        local att_risks = {}

                        if att.extension_mismatch then
                            local declared_ext = string.match(fname, "%.([^.]+)$") or "?"
                            table.insert(att_risks,
                                "扩展名不匹配(声明." .. declared_ext ..
                                ",实际" .. label .. ")")
                        end
                        if att.is_macro_capable then
                            table.insert(att_risks, "含宏能力")
                        end
                        if _DANGEROUS_LABELS[label] then
                            table.insert(att_risks, "高风险类型(" .. label .. ")")
                        end

                        if #att_risks > 0 then
                            table.insert(warnings,
                                fname .. ": " .. table.concat(att_risks, ","))
                        end
                    end
                end
            end
        end
    end

    if #warnings == 0 then
        return ""
    end
    return "【附件风险提示】" .. table.concat(warnings, "; ")
end

-- 调用secbot工作流
local function call_ai_service(task)
    local sender = task:get_from("smtp")
    sender = sender and sender[1] and sender[1]["addr"] or ""

    rspamd_logger.infox(task, "AI检测：开始处理，发件人: %s", sender)

    if is_internal_domain(sender) then
        rspamd_logger.infox(task, "AI检测：跳过内部域名")
        return
    end

    local subject = sanitize_body(task:get_header("Subject") or "")
    local raw_body = task:get_content() or ""
    local body = sanitize_body(raw_body)
    local urls = extract_urls(task)
    local rspamd_score = task:get_metric_score()[1] or 0

    local urls_json = ucl.to_format(urls, "json-compact")
    local attachments_json = extract_attachments(task)
    rspamd_logger.infox(task, "AI检测：附件提取完成: %s",
        attachments_json == '[]' and '无附件' or '有附件')
    local recipient = ""
    local recipients = task:get_recipients("smtp")
    if recipients and recipients[1] and recipients[1]["addr"] then
        recipient = sanitize_body(recipients[1]["addr"])
    end
    sender = sanitize_body(sender)
    subject = sanitize_body(subject)
    local post_data = {
        inputs = {
            sender = sender,
            subject = subject,
            body = body,
            urls = urls_json,
            recipient = recipient,
            rspamd_score = string.format("%.2f", rspamd_score),
            attachments = attachments_json,
        },
    }

    local function http_callback(err, code, resp_body, headers)
        rspamd_logger.infox(task, "AI回调触发: err=%s, code=%s",
            tostring(err), tostring(code))

        if err then
            rspamd_logger.errx(task, "secbot 工作流调用失败: %s", err)
            return
        end

        if code ~= 200 then
            rspamd_logger.errx(task,
                "secbot 工作流 HTTP 异常: code=%s, body=%s",
                tostring(code), tostring(resp_body))
            return
        end

        local result, perr = parse_workflow_response(resp_body)
        if not result then
            rspamd_logger.errx(task,
                "无法从 step3.stdout 解析 add_score (%s)，默认 add_score=0", tostring(perr))
            return
        end

        -- 参照 trellis 版本：使用 tonumber 并检查 nil，避免字符串类型导致 insert_result 失败
        local add_score = tonumber(result.add_score)
        if not add_score then
            rspamd_logger.errx(task,
                "step3.stdout 缺少 add_score 字段，默认 add_score=0: %s",
                tostring(resp_body))
            return
        end

        local is_phishing = result.is_phishing == true or (tonumber(result.confidence) or 0) > 0.5
        local confidence = tonumber(result.confidence) or 0.0
        local reason = tostring(result.reason or "")
        local suggested_action = tostring(result.suggested_action or "")
        local from_cache = result.from_cache == true

        -- score=1.0 时 insert_result 的 weight=0 会触发默认分(1.0)，
        -- 因此 add_score<=0 时跳过 insert_result 避免误加基础分
        if add_score > 0 then
            task:insert_result("AI_PHISHING_DETECT", add_score, {
                is_phishing = is_phishing,
                confidence = confidence,
                reason = reason,
                action = suggested_action,
                from_cache = tostring(from_cache),
            })
        else
            rspamd_logger.infox(task, "AI检测完成 | add_score=0，跳过加分 | 理由: %s", reason)
        end

        -- 生成附件风险警告邮件头，让用户在查看邮件时看到提示
        -- 只检查附件自身的客观风险（扩展名不匹配/宏能力/高危类型）
        -- 不使用 LLM 的 risk_factors，避免正常附件被误标
        local attachments_json_str = tostring(result.attachments_json or "[]")
        local attachment_warning = build_attachment_warning(attachments_json_str)
        if attachment_warning and attachment_warning ~= "" then
            -- 获取解码后的原始主题，在主题前加 [附件风险] 标记
            -- Thunderbird 不显示自定义 X- 头，修改主题是最直观的提示方式
            local subject_full = task:get_header_full("Subject")
            local original_subject = ""
            if subject_full and subject_full[1] then
                original_subject = subject_full[1].decoded or subject_full[1].value or ""
            end
            local new_subject = "[附件风险] " .. original_subject

            -- Rspamd 4.x 使用 set_milter_reply 添加邮件头
            -- remove_headers 删掉旧 Subject，add_headers 写入新 Subject + 风险警告头
            task:set_milter_reply({
                remove_headers = { ["Subject"] = 1 },
                add_headers = {
                    ["Subject"] = new_subject,
                    ["X-Attachment-Risk-Warning"] = attachment_warning,
                },
            })
            rspamd_logger.infox(task, "附件风险警告已写入: 主题=%s, 头=%s", new_subject, attachment_warning)
        end

        -- 预格式化数字为字符串，避免中文格式串中 %.2f 不渲染的问题
        rspamd_logger.infox(task,
            "AI检测完成 | 钓鱼: %s | 置信度: %s | 加分: %s | 缓存: %s | 动作: %s",
            tostring(is_phishing),
            string.format("%.2f", confidence),
            string.format("%.1f", add_score),
            tostring(from_cache),
            suggested_action)
    end

    rspamd_logger.infox(task, "正在调用 secbot 工作流: %s", ai_config.workflow_run_url)
    local headers = { ["Content-Type"] = "application/json" }
    rspamd_http.request({
        task = task,
        url = ai_config.workflow_run_url,
        method = "POST",
        headers = headers,
        body = ucl.to_format(post_data, "json-compact"),
        timeout = ai_config.request_timeout,
        callback = http_callback,
    })
end

-- 主回调（postfilter 类型，确保拿到最终分数）
-- 所有邮件均进入 workflow，由 workflow step2 condition 决定是否调用 LLM
rspamd_config:register_symbol({
    name = "AI_PHISHING_DETECT",
    type = "postfilter",
    callback = function(task)
        rspamd_logger.infox(task, "AI_PHISHING_DETECT 插件被触发")

        if not ai_config.enabled then
            rspamd_logger.infox(task, "插件已禁用，退出")
            return
        end

        local score = task:get_metric_score()[1] or 0
        rspamd_logger.infox(task, "当前邮件分数: %.2f，调用工作流处理", score)
        call_ai_service(task)
    end,
    score = 1.0,
    group = "phishing",
    description = "AI增强钓鱼邮件检测",
})
