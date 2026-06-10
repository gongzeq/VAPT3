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
    workflow_run_url = "http://10.10.122.91:18791/api/workflows/wf_ec5d48a3/run",
    request_timeout = 130,
    internal_domains = { "gdmsa1.gov.cn" },
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

-- 提取邮件URL
local function extract_urls(task)
    local urls = {}
    local parts = task:get_urls()
    if parts then
        for _, u in ipairs(parts) do
            table.insert(urls, u)
        end
    end
    return urls
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

-- 解析 workflow 响应：从 stepResults.step3.output 提取结果
local function parse_workflow_response(body)
    local parser = ucl.parser()
    local ok, err = parser:parse_string(body)
    if not ok then
        return nil, "parse body failed: " .. tostring(err)
    end
    local obj = parser:get_object()
    if type(obj) ~= "table" then
        return nil, "body is not object"
    end
    -- API 返回 stepResults（camelCase）或 step-results（kebab-case）
    local step_results = obj.stepResults or obj["step-results"] or obj["stepResults"]
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
    -- 提取 stdout 字符串，直接用模式匹配解析 JSON（避开 UCL 键名转换）
    local stdout = output.stdout
    if type(stdout) ~= "string" and type(stdout) ~= "userdata" then
        return nil, "stdout is not string (type=" .. type(stdout) .. ")"
    end
    local stdout_str = tostring(stdout)
    if stdout_str == "" then
        return nil, "stdout is empty"
    end
    local add_score = tonumber(string.match(stdout_str, '"add_score"%s*:%s*(-?%d+%.?%d*)')) or 0.0
    local confidence = tonumber(string.match(stdout_str, '"confidence"%s*:%s*(-?%d+%.?%d*)')) or 0.0
    local reason = string.match(stdout_str, '"reason"%s*:%s*"([^"]*)"') or ""
    local suggested_action = string.match(stdout_str, '"suggested_action"%s*:%s*"([^"]*)"') or ""
    return {
        add_score = add_score,
        confidence = confidence,
        reason = reason,
        suggested_action = suggested_action,
    }, nil
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

        -- parse_workflow_response 返回干净的 Lua 表
        local add_score = result.add_score or 0.0
        local confidence = result.confidence or 0.0
        local is_phishing = (confidence > 0.5)
        local reason = result.reason or ""
        local suggested_action = result.suggested_action or ""

        task:insert_result("AI_PHISHING_DETECT", add_score, {
            is_phishing = is_phishing,
            confidence = confidence,
            reason = reason,
            action = suggested_action,
        })

        -- 预格式化数字为字符串，避免中文格式串中 %.2f 不渲染的问题
        rspamd_logger.infox(task,
            "AI检测完成 | 钓鱼: %s | 置信度: %s | 加分: %s | 动作: %s",
            tostring(is_phishing),
            string.format("%.2f", confidence),
            string.format("%.1f", add_score),
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
