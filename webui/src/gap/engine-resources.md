# Gap: Engine Resources Page

## 后端缺口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/engines` | GET | 列出引擎资源（扫描工具/脚本/字典） |
| `/api/engines` | POST | 上传新引擎资源（multipart） |
| `/api/engines/{id}` | DELETE | 删除引擎资源 |
| `/api/engines/{id}/toggle` | PUT | 启用/禁用引擎 |

**数据模型**：`Engine { id, name, version, kind: "scanner"|"dictionary"|"script", enabled, size_bytes, uploaded_at, uploaded_by }`

## 前端预计表现

- 列表卡 + 上传按钮（隐藏 `<input type="file">` + useRef 触发）
- 每行：名称 + 版本 + 类型徽章 + 启用/禁用开关 + 删除（二次确认模态）
- 文件上传进度条
- 角色门：非 admin 只读

## Mock 数据

后续放置于 `src/data/mock/engines.ts`。

## 建议后续任务

1. 后端 `/api/engines` CRUD + 文件存储（本地或 S3）
2. 前端 EngineResourcesPage + hook `useEngines`
3. 上传体积/格式校验
