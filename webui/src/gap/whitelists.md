# Gap: Whitelists Page

## 后端缺口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/whitelists` | GET | 列出所有白名单（分页 `page/page_size`） |
| `/api/whitelists` | POST | 新建白名单项（`{ target, reason, expires_at? }`） |
| `/api/whitelists/{id}` | DELETE | 删除白名单项 |

**数据模型**：`Whitelist { id, target, reason, created_by, created_at, expires_at }`

## 前端预计表现

- 单卡列表布局 + "新增" 按钮 → 模态框表单
- 每行：target（font-mono）+ reason + 创建时间 + 删除按钮（二次确认）
- 空态卡 + loading 骨架屏

## Mock 数据

后续放置于 `src/data/mock/whitelists.ts`（PR7 不含实现，仅文档）。

## 建议后续任务

1. 后端实现 `/api/whitelists` CRUD（挂到 aiohttp 子服务）
2. 前端 WhitelistsPage 落地 + hook `useWhitelists`
3. 鉴权门：仅 admin 可写
