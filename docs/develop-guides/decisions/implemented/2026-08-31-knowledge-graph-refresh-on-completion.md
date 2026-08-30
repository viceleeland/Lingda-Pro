# 图谱构建完成后刷新画布

状态：implemented
类型：bug-fix
Owner：web/src/components/KnowledgeGraphSection.vue

## 问题

知识图谱后台任务完成后，状态卡已经显示 completed，但画布仍可能保留构建前数据，用户必须手动点击刷新才能看到新实体和关系。

## 决策

监听构建活动状态从 active 转为非 active；只有上一个状态确实在构建且最终任务状态为 completed 时，立即调度一次图数据加载。失败、取消、初次挂载和普通状态刷新不触发这条完成刷新。

## 替代方案

- 每次轮询都刷新图数据：实现简单，但会对 Neo4j/API 和画布布局造成持续额外负载。
- 仅显示“请手动刷新”：没有竞态，但保留了已知的用户操作缺口。
- 后端通过新事件主动推送：时效最好，但为一个页面终态增加新的协议与维护面。

## 后果

一次成功构建完成后画布自动读取最新数据；现有轮询和手动刷新仍可使用。刷新属于幂等读取，不改变图谱任务或索引状态。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| active → completed 后刷新一次 | 状态完成但画布陈旧 | `KnowledgeGraphSection.vue` | Web unit/source contract、真实图谱页回读 | 初次 inactive 不得触发完成刷新 | Passed |
| failed/cancelled 不冒充成功刷新 | 错误终态显示成最新成功图 | 同上 | 条件分支审查 | 仅 completed 命中 | Passed |
| 图谱数据与索引终态一致 | UI 刷新后仍缺实体/关系 | Compose 图谱链路 | 1,063 Chunk、12,428 实体、16,744 三元组，任务 remaining=0 | pending/running 必须为 0 | Passed |
