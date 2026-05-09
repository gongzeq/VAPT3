# Gap: Role Gate (Admin 角色门)

## 后端缺口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/auth/me` | GET | 返回当前用户信息（含 `role`） |

**数据模型**：`UserProfile { id, username, role: "admin"|"viewer", created_at }`

## 当前临时方案

- **无真实角色系统**：当前 bootstrap secret 鉴权不区分角色，所有通过鉴权的用户等同 admin。
- **Mock 路径**：后续可用 `localStorage['secbot.fakeRole'] = 'viewer'` 模拟非 admin 角色，用于前端 UI 测试。
- 前端守卫函数签名：`useRole(): { role: 'admin' | 'viewer', isAdmin: boolean }`

## 影响范围

以下页面需要角色门：
- Whitelists（写操作）
- Engine Resources（上传/删除）
- Platform Settings（写操作）
- Audit Log（访问权限）
- Settings 危险区（清空会话）

## 建议后续任务

1. 后端 `/api/auth/me` 端点 + 用户表
2. 前端 `useRole` hook + `<AdminGate>` 组件
3. 非 admin 友好空态卡（"联系管理员获取权限"）
4. 鉴权令牌中嵌入 role claim（JWT sub+role）
