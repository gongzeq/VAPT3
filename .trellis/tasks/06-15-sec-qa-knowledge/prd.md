# 网络安全问答子智能体 + 知识库

## Goal

为 secbot 增加一个**网络安全知识问答子智能体(`sec_qa`)**,配合一个**小规模安全知识库**(几 MB 级 markdown),采用 **secbot Python grep 主力 + 向量 fallback** 的轻量双层检索架构。目标是让安全人员在 VAPT 任务过程中能即时咨询安全知识(漏洞原理、攻击手法、CVE 详情、方法论等),无需外部浏览器/搜索跳转。

## Decision (ADR-lite)

**Context**:需要在"重型 RAG 框架"与"极简检索"之间选择最适合几 MB 知识库的方案。

**决策**:
- ❌ RAG-Anything(MinerU + torch,GB 级,杀鸡用牛刀)
- ❌ LightRAG(知识图谱抽取烧 token,几 MB 规模过度设计)
- ❌ 独立向量库(ChromaDB/FAISS 引入重依赖)
- ❌ ripgrep 二进制(几 MB 规模 Python re 已够用,避免外部二进制依赖)
- ✅ **secbot Python grep + 向量 fallback**(零新依赖,numpy 复用)
- ✅ **新建子智能体**(而非挂到 Orchestrator prompt):职责隔离,防止 prompt 臃肿
- ✅ **向量索引存 JSON 单文件**:无数据库,简单可控
- ✅ **与 secknowledge-skill 完全解耦**:不迁移、不整合

**Consequences**:
- 知识库规模 < 50 MB 时性能充足;若超过,需评估升级 ripgrep 或引入向量库
- 向量层依赖 OpenAI 兼容 `/embeddings` 接口,网络不可用时自动降级为纯 grep
- 无双数据库运维负担,JSON 文件损坏可一键重建

## Requirements

**R1. 子智能体定义**
- 新增 `secbot/agents/sec_qa.yaml`(遵循 [vuln_scan.yaml](file:///home/administrator/VAPT3/secbot/agents/vuln_scan.yaml) 模板)
- 新增 `secbot/agents/prompts/sec_qa.md`(角色:网络安全知识顾问)
- `scoped_skills` 声明一个新建的 `knowledge-search` Skill
- `max_iterations: 5`(知识问答不需要长链迭代)
- `endpoint_bound: false`(非端点绑定型任务)

**R2. knowledge-search Skill**
- 新增 `secbot/skills/knowledge-search/` 目录
- `SKILL.md`:定义工具描述、路由规则、执行流程
- `handler.py`:包含 `KnowledgeSearchTool`(继承 `Tool`)
- 检索流程:LLM 关键词扩展 → Python grep 并行搜 → 命中不足时向量 fallback
- 返回格式:相关文档片段 + 来源文件 + 行号

**R3. 知识库存储**
- 新增目录 `secbot/knowledge/docs/`(markdown 原文,git 管理)
- 初始分类子目录:`web-security/`、`cve-archive/`、`methodologies/`、`ai-security/`
- 新增 `.gitignore` 规则排除索引产物

**R4. 向量层**
- `secbot/knowledge/vector_index.py`:极简实现(切片 + JSON 缓存 + numpy 余弦)
- 落盘文件:单文件 JSON `secbot/knowledge/vector_cache.json`(gitignore,~15-30 MB)
- **不使用任何数据库**(无 SQLite/ChromaDB/PostgreSQL)
- 结构:`[{"text": "...", "source": "web-security/xss.md", "chunk_id": 3, "embedding": [...]}, ...]`
- 加载时 numpy 构建内存矩阵,查询走余弦相似度 Top-K
- 仅在 grep 命中率不足时启用(自动降级)
- embedding 调用复用现有 OpenAI 兼容 provider 的 `/embeddings` 接口

**R5. CLI 命令**
- 新增 `secbot knowledge index` 命令(在 `secbot/cli/commands.py` 注册)
- 支持全量构建和增量更新(基于文件 mtime 判断)
- 构建过程:扫描 `docs/` → 切片 → 批量 embedding → 写 `vector_cache.json`

**R6. Orchestrator 触发**
- Orchestrator 自动识别"问答型意图"并派发给 `sec_qa`
- 无需用户记命令前缀
- 在 `sec_qa.yaml` 的 `description` 字段中明确写出路由规则,让 Orchestrator LLM 能正确匹配

**R7. 与 secknowledge-skill 解耦**
- `secknowledge-skill` 保持现状不动
- `secbot/knowledge/` 作为完全独立的新模块

## Acceptance Criteria

* [ ] `secbot/agents/sec_qa.yaml` 和 `prompts/sec_qa.md` 通过 [AgentRegistry](file:///home/administrator/VAPT3/secbot/agents/registry.py) 正确加载
* [ ] `knowledge-search` Skill 被正确发现并可注册
* [ ] Orchestrator 能识别并将问答任务派发给 `sec_qa`
* [ ] `KnowledgeSearchTool` 对典型安全问题(如"XSS 原理"、"CVE-2024-XXX")返回相关片段
* [ ] 向量 fallback 在 grep 命中不足时自动启用
* [ ] embedding API 不可用时自动降级为纯 grep(无报错中断)
* [ ] `secbot knowledge index` 命令可成功构建向量索引
* [ ] 新增文档到 `docs/` 后,增量索引能正确更新
* [ ] `sec_qa` 子智能体无法调用扫描类工具(权限隔离)
* [ ] 单元测试覆盖:向量余弦排序、grep 检索路径、降级逻辑、CLI 命令

## Definition of Done

* 单元测试覆盖核心路径(向量索引、grep 检索、降级、CLI)
* Lint / typecheck 通过
* 向量层可通过配置开关关闭(退化为纯 grep)
* 知识库目录有至少 2-3 个示例 markdown 用于验证

## Out of Scope

* ❌ 多模态文档解析(PDF/DOCX 转换脚本可后续单独加)
* ❌ 知识图谱抽取(不引入 LightRAG)
* ❌ 独立向量数据库(ChromaDB/FAISS/Milvus)
* ❌ 多轮对话 session 管理(MVP 仅单轮)
* ❌ WebUI 层面的知识库管理界面
* ❌ 本地 embedding 模型(复用 OpenAI 兼容 API)
* ❌ 对 secknowledge-skill 的任何修改

## Implementation Plan

### Task 1: 知识库目录 + 示例文档
- 创建 `secbot/knowledge/docs/` 及分类子目录
- 放入 2-3 个示例 markdown(从 OWASP Top 10 摘录)
- 添加 `.gitignore` 排除 `vector_cache.json`

### Task 2: 向量索引模块
- 实现 `secbot/knowledge/vector_index.py`(SimpleVectorIndex)
- 切片逻辑(markdown heading-aware)
- JSON 持久化 + numpy 余弦相似度
- embedding 调用(复用 OpenAI 兼容 provider)
- 单元测试

### Task 3: knowledge-search Skill
- 创建 `secbot/skills/knowledge-search/SKILL.md`
- 实现 `handler.py` 中的 `KnowledgeSearchTool`
- 流程:LLM 关键词扩展 → grep 搜 → 向量 fallback
- 注册到 subagent tool building 流程
- 单元测试

### Task 4: sec_qa 子智能体
- 创建 `secbot/agents/sec_qa.yaml`
- 创建 `secbot/agents/prompts/sec_qa.md`
- 确保通过 AgentRegistry 验证
- 集成测试:Orchestrator → sec_qa → KnowledgeSearchTool → 返回结果

### Task 5: CLI 命令
- 在 `secbot/cli/commands.py` 注册 `secbot knowledge index`
- 全量 + 增量构建逻辑
- 单元测试

### Task 6: Orchestrator 路由 + 集成验证
- 确保 `sec_qa.yaml` description 字段足够清晰,Orchestrator 能正确路由
- 端到端测试:用户提问 → Orchestrator 派发 → sec_qa 检索 → 回答
