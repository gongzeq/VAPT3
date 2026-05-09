# Gap: Audit Log Page

## 后端缺口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/audit-logs` | GET | 分页查询审计日志（`page/page_size/action?/user?/since?/until?`） |

**数据模型**：`AuditLog { id, timestamp, user, action, resource_type, resource_id, detail, ip_address }`

**写入端**：内部中间件自动记录（登录/登出/扫描启动/配置变更/白名单操作等），不暴露写 API。

## 前端预计表现

- 表格布局：时间 | 用户 | 操作 | 资源 | IP
- 筛选栏：action 类型下拉 + 时间范围选择器
- 分页：上/下一页 + ChevronLeft/Right
- 角色门：仅 admin 可访问

## Mock 数据

后续放置于 `src/data/mock/audit-logs.ts`。

## 建议后续任务

1. 后端审计中间件 + `/api/audit-logs` 查询端点
2. 前端 AuditLogPage + hook `useAuditLogs`
3. 日志保留策略（自动清理 > 90 天）
