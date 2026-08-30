# 模型重试耗尽后写入失败终态

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/agents/buildin/chatbot/graph.py

## 问题

根智能体和子智能体曾使用 `ModelRetryMiddleware` 的默认失败策略。模型调用重试耗尽时，中间件会把异常转换为普通 AIMessage，后续链路将错误文字当作正常回答保存，并把 AgentRun 与 attempt 提交为 `completed`。这会让 PostgreSQL、Redis 终态和真实执行结果不一致。

## 决策

- 根智能体与子智能体显式配置 `ModelRetryMiddleware(on_failure="error")`，让重试耗尽后的原始异常进入既有 `error → failed` 终态链路。
- 重试次数、退避、正常回答、工具错误和成功终态行为保持不变。
- 实际装配的中间件由参数化 unit 约束；确定性 E2E 使用带唯一错误标记的受控 503，真实页面故障注入补充验证 SSE、Run、attempt 与输出消息的失败因果关系。

## 替代方案

- 在消息持久化或 repository 层匹配 `Model call failed` 文案：依赖第三方可变字符串，也可能误伤真实回答，拒绝。
- 在所有 AIMessage 中新增通用错误分类：为两个明确装配点引入新的协议和维护表面，超出本次修复范围，拒绝。
- 仅修根智能体：子智能体保留相同错误终态缺陷，不符合统一 AgentRun 状态语义，拒绝。

## 后果

模型重试耗尽后，用户看到既有结构化错误展示；数据库和 SSE 均记录 `failed`，不再发布 `response_complete` 或正常错误回答。PostgreSQL 与日志保留原始异常用于问责，对外 Run view、SSE 和结果接口按公开错误类型映射固定安全文案。错误类型仍由现有 chat/worker 异常映射拥有，本决定不增加新的状态机。

本地确定性 E2E 因未配置独立 E2E 凭据而显式 skip；replay 服务器的受控 503 契约已独立通过。登录页面中的临时失败 provider 真实执行后，Redis 与 PostgreSQL 回读也满足失败终态，临时 Agent、provider 与 Conversation 随后删除。CI 的 assembled-path workflow 继续执行完整 E2E 用例。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 根智能体重试耗尽后抛出异常 | 错误文字仍成为普通回答 | `chatbot/graph.py` | `test_summary_graph_config.py` | middleware 恢复默认值时断言得到 `continue` | Passed：负控修改前失败，修改后参数化 unit 通过 |
| 子智能体采用相同失败语义 | 子 Run 仍错误 completed | `subagent/graph.py` | 同一参数化 unit | 子智能体实际 middleware 的 `on_failure` 必须为 `error` | Passed |
| worker 将流错误写为 failed | 异常传播后仍错误完成，或内部异常经公开接口泄露 | `chat_service.py` / `run_worker.py` / `agent_run_service.py` / PostgreSQL | 受控 503 E2E；Chrome 真实失败请求；Redis/PostgreSQL 回读 | 唯一错误标记只保留在 PostgreSQL 原始 `error_message`；公开 error SSE、Run view 与结果接口必须返回固定安全文案；不得出现 `response_complete`、正常 `Model call failed` 消息或 `end:completed` | Passed with local integration gap：Run/attempt=`failed`，事件为 `error → end:failed`；公共投影 service unit 55/55，通过；HTTP integration 已新增，但本地因未配置 `TEST_USERNAME` / `TEST_PASSWORD` 而 skip |
| 正常模型回答不回退 | 成功请求被误标 failed | 同上 | 参数化 middleware unit 与既有完成/retry worker unit | 正常 finished 仍提交 completed | Passed：精确相关 9 个 unit 全部通过 |
