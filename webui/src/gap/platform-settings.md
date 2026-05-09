# Gap: Platform Settings Page

## 后端缺口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/platform/config` | GET | 获取平台全局配置 |
| `/api/platform/config` | PUT | 更新平台全局配置 |

**数据模型**：`PlatformConfig { scan_concurrency, default_timeout_s, notification_webhook?, retention_days, require_approval_for_critical }`

## 前端预计表现

- 表单卡布局：每个配置项一行（label + input/select + help text）
- 保存按钮 + loading 状态
- 422 错误内联到字段下方
- 角色门：仅 admin 可修改，非 admin 只读展示

## Mock 数据

后续放置于 `src/data/mock/platform-config.ts`。

## 建议后续任务

1. 后端 `/api/platform/config` 读写端点（持久化到 config.yaml 或 DB）
2. 前端 PlatformSettingsPage + hook `usePlatformConfig`
3. 配置变更自动写入审计日志
