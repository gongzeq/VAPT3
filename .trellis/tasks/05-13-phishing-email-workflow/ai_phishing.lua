local rspamd_logger = require "rspamd_logger"
local rspamd_http = require "rspamd_http"
local rspamd_util = require "rspamd_util"
local ucl = require "ucl"

-- 配置：调用 secbot 钓鱼邮件检测工作流（替代下线的 ai_detector.py:5001）
-- 来源：.trellis/tasks/05-13-phishing-email-workflow/prd.md §R2
-- 部署步骤：
--   1. 先在 WebUI 用钓鱼邮件检测模板"Use"出一个 workflow，记下 wf_id
--   2. 把下面的 workflow_run_url 末尾的 <wf_id> 替换为该 ID
--   3. 如果 secbot 启用了 bearer token，填到 auth_token；否则保持 ""
local ai_config = {
    enabled = true,
    -- secbot workflow run 端点。``<wf_id>`` 必须替换为实际工作流 ID。
    workflow_run_url = "http://127.0.0.1:18791/api/workflows/wf_6ce140c2/run",
    auth_token = "sk-b7c70caf48e145a58156596b7462a685",
    request_timeout = 120,
    min_score = -10,
    max_score = 10.0,
    internal_domains = { "gdmsa.cn" },
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
            -- 兼容两种格式：URL对象 或 纯字符串
            local url_str

            -- 如果是对象，并且有 get_text 方法
            if type(u) == 'table' and u.get_text then
                url_str = u:get_text()
            else
                -- 如果是纯字符串，直接用
                url_str = tostring(u)
            end

            if url_str and url_str ~= "" then
                table.insert(urls, url_str)
            end
        end
    end

    return urls
end

-- 安全解析 step3 stdout 的 JSON。secbot workflow run 响应结构：
--   { stepResults = { step3 = { output = { stdout = "<JSON 字符串>" } } } }
-- step3 的 stdout 契约（PRD §Technical Approach）：
--   { add_score, is_phishing, confidence, reason, suggested_action, from_cache, ... }
local function parse_workflow_response(body_text)
    if not body_text or body_text == "" then
        return nil, "empty body"
    end
    local parser = ucl.parser()
    local ok, err = parser:parse_string(body_text)
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
    if type(stdout) ~= "string" or stdout == "" then
        return nil, "missing step3.output.stdout"
    end
    local inner = ucl.parser()
    local ok2, err2 = inner:parse_string(stdout)
    if not ok2 then
        return nil, "stdout parse failed: " .. tostring(err2)
    end
    local result = inner:get_object()
    if type(result) ~= "table" then
        return nil, "stdout not object"
    end
    return result, nil
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

    local subject = task:get_header("Subject") or ""
    local body = task:get_content() or ""
    local urls = extract_urls(task)
    local rspamd_score = task:get_metric_score()[1] or 0

    -- secbot workflow run 协议：``{"inputs": {...}}``
    -- urls 以 JSON 字符串传入（WorkflowInput 类型为 string）
    local urls_json = ucl.to_format(urls, "json-compact")
    local recipient = ""
    local recipients = task:get_recipients("smtp")
    if recipients and recipients[1] and recipients[1]["addr"] then
        recipient = recipients[1]["addr"]
    end
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
            -- 容错策略（PRD §R5）：解析不到 add_score 时默认放行（不加分）
            rspamd_logger.errx(task,
                "无法从 step3.stdout 解析 add_score (%s)，默认 add_score=0", tostring(perr))
            return
        end

        local add_score = tonumber(result.add_score)
        if not add_score then
            rspamd_logger.errx(task,
                "step3.stdout 缺少 add_score 字段，默认 add_score=0: %s",
                tostring(resp_body))
            return
        end

        local is_phishing = result.is_phishing == true
        local confidence = tonumber(result.confidence) or 0.0
        local reason = result.reason or ""
        local suggested_action = result.suggested_action or ""
        local from_cache = result.from_cache == true

        task:insert_result("AI_PHISHING_DETECT", add_score, {
            is_phishing = is_phishing,
            confidence = confidence,
            reason = reason,
            action = suggested_action,
            from_cache = tostring(from_cache),
        })

        rspamd_logger.infox(task,
            "AI检测完成 | 钓鱼: %s | 置信度: %.2f | 加分: %.1f | 缓存: %s | 理由: %s",
            tostring(is_phishing), confidence, add_score,
            tostring(from_cache), reason)
    end

    rspamd_logger.infox(task, "正在调用 secbot 工作流: %s", ai_config.workflow_run_url)
    local headers = { ["Content-Type"] = "application/json" }
    if ai_config.auth_token and ai_config.auth_token ~= "" then
        headers["Authorization"] = "Bearer " .. ai_config.auth_token
    end
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
        rspamd_logger.infox(task, "当前邮件分数: %.2f (触发区间: %.2f - %.2f)", score, ai_config.min_score, ai_config.max_score)

        if score >= ai_config.min_score and score <= ai_config.max_score then
            rspamd_logger.infox(task, "分数符合，调用AI检测...")
            call_ai_service(task)
        else
            rspamd_logger.infox(task, "分数不在触发区间，跳过AI检测")
        end
    end,
    score = 0.0,
    group = "phishing",
    description = "AI增强钓鱼邮件检测",
})