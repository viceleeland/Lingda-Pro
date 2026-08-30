# 降低智能体首字与可见收尾延迟

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/services/chat_service.py

## 问题

默认知识库智能体回答“你好”时，真实页面约 13～18 秒后才显示首字；正文已经完整显示后，“正在生成回复”仍继续显示约 8 秒。运行事件证明模型正文生成只占很小一段时间，主要延迟来自重复解析知识库资源、同一轮重复构建 LangGraph，以及在可见回复状态内同步完成运行时清理。简单问候还向模型暴露了与知识库问答无关的通用工具和子智能体。

## 决策

- 当前验收部署的默认知识库智能体只预加载 `concise-rag`，不配置其他普通工具、MCP 或 Skill；这是实例数据库配置，不改变通用产品的默认 Agent bootstrap。
- 通过独立开关关闭文件/待办、长期记忆和子智能体中间件；普通用户执行管理员保存的 Agent 配置时仍保留这些开关值。
- 纯知识库 Agent 使用 LangGraph `StateBackend` 保存内部 summary 状态，不物化 Docker sandbox；实际需要沙箱的显式工具或 Skill 工具由注册元数据统一声明并自动恢复 sandbox runtime。
- 关闭工作区工具时只装配并提示已预加载 Skill；依赖 `read_file` 激活的 lazy Skill 不进入可用集合，避免向模型宣告无法执行的能力。
- 资源可见性解析复用当前数据库会话，避免同一 worker 内为知识库列表打开嵌套会话。
- 同一次运行时准备只解析一次可见知识库，并复用于资源规范化和工具上下文。
- 一次 AgentRun 显式复用同一个已编译 graph 完成流式输出、状态读取、中断检查和消息持久化。
- 模型输出完成后发布非终态的 `response_complete` 事件；前端据此停止“正在生成回复”，但仍以 PostgreSQL Run 终态和 `end` 事件作为允许下一轮派发、断线恢复和最终事实的唯一依据。
- 未创建 sandbox 的轻量 Run 在终态事务中关闭空 cleanup fence；实际创建 sandbox 的路径继续保持原有 cleanup 与 SSE `end` 时序。

## 替代方案

- 只调提示词：不能消除框架初始化、重复构图和 runtime cleanup 延迟。
- 在持久化或 runtime cleanup 前发布 `end`：会破坏终态事件与 PostgreSQL/runtime cleanup 的时序约束，并可能让下一轮运行撞上前一轮沙箱清理。
- 为问候增加硬编码答案：只能掩盖单个输入，不能改善所有走 LLM 的请求。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 同一轮只构建一次 graph | 收尾阶段仍重复加载模型与中间件 | `ChatbotAgent.get_graph` / `stream_agent_chat` | chat/resume unit + 真实 worker 日志 | 恢复重复构图后次数断言失败 | Passed：chat 与 resume 均复用请求内 graph |
| 知识库资源解析不创建嵌套会话或重复查询 | 首字前固定等待数秒 | `resolve_agent_resource_options` | repository/context unit + 查询次数断言 | 第二次解析可见 KB 时断言失败 | Passed：同一 session、prepare 内一次解析 |
| 正文完成后立即隐藏生成提示 | UI 在后台清理期间仍宣称生成 | `useAgentStreamHandler` | Web unit + Chrome/Redis 真实页面计时 | `response_complete → error` 仍须终止并显示公开错误 | Passed：同一武汉问题正常样本首字 5.737s、正文结束 7.170s、`response_complete` 7.194s、`end` 7.286s，正文到提示消失尾差 0.024s |
| 终态与清理契约保持有效 | UI 乐观结束导致下一轮撞上清理 | `run_worker` / PostgreSQL AgentRun | 37 worker unit + PostgreSQL integration + Run 回读 | sandbox 工具或子智能体启用时不得关闭 cleanup fence | Passed：真实 Run `completed`、`runtime_cleanup_pending=false`；integration 通过 |
| 轻量 summary 不丢证据、不污染 UI 文件区 | StateBackend 缺通道、内部文件不可读或误展示 | `BaseState` / summary / `extract_agent_state` | 真实 StateGraph write + summary unit + UI 投影 unit | 大工具结果不得截断到不可读路径 | Passed：StateBackend 有 `files` channel，轻量模式保留全文，内部目录不投影 |
| 关闭工作区后不提示不可激活的 lazy Skill | 模型被要求读取不存在的 `read_file` | Skill runtime / `SkillsMiddleware` | middleware、ToolNode 注册与 backend runtime unit | 非预加载 Skill 不得出现在提示或依赖工具集合 | Passed |
| 知识库图片、公式、表格与引用能力不回退 | 为速度关闭必要 RAG 工具 | `精简 RAG` 与知识库工具 | Chrome 真实 UI 回归问答 | 通用餐饮问题不得试探查库 | Passed：Figure 55/56 同页图 1224×1584 正常加载；公式 3 个 KaTeX 节点、2 个 display 且无裸 `$$`；Table 18 为真实 HTML 表格；武汉美食工具调用 0 |

## 后果

知识库专用 Agent 的模型工具上下文和运行时初始化明显缩小；通用问题与 CAE 知识问题由提示词边界分流。正文完成提示不再等待后台持久化或清理，活动 Run、断线恢复和下一轮派发仍服从 PostgreSQL 终态及 SSE `end`。

- `response_complete` 只能控制回复生成提示，不能把 Run 标记为终态，也不能提前清空活动 Run。
- graph 只能在同一个运行上下文内复用，不能跨用户、线程或 Run 缓存。
- 资源查询必须继续执行权限过滤；优化只允许复用当前授权会话，不能用长期缓存绕过权限变化。
- 新增沙箱工具必须在注册元数据中声明 `requires_workspace_runtime`，不能在调用点维护旁路名单。
- `concise-rag`、模型和知识库绑定属于当前部署实例；新部署不会自动获得该私有 Skill 或固定知识库 ID，必须由管理员显式配置。
- 轻量 StateBackend 中的 summary 内部文件不得投影到用户文件面板；因未开放 `read_file`，工具结果必须保留完整正文而不能截断成不可恢复路径。
- 本决策消除的是本地固定开销和可见收尾延迟，不承诺外部模型的每次首字时延。一次同题同配置请求出现 67.238s 的 DeepSeek 请求阶段长尾，而直接重跑为 5.292s；两次均无工具调用，不能用提示词或关闭知识库掩盖上游偶发长尾。
