<div align="center">

<img src="web/public/favicon.svg" width="72" height="72" alt="灵答升级版" />

# 灵答升级版 · Lingda-Pro

**面向专业资料的知识检索与智能体协作平台**

图文资料入库 · 来源可追溯 · 多步骤任务 · 私有部署

[快速启动](#快速启动) · [核心能力](#核心能力) · [技术架构](ARCHITECTURE.md) · [English](README.en.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-0F766E)](LICENSE)
[![Deploy: Docker Compose](https://img.shields.io/badge/Deploy-Docker_Compose-2496ED)](docker-compose.yml)
[![Vue 3 + FastAPI](https://img.shields.io/badge/Stack-Vue_3_%2B_FastAPI-334155)](https://github.com/viceleeland/Lingda-Pro)

</div>

---

灵答升级版将文档解析、知识检索、智能体执行和成果管理整合在一个工作区。面向技术手册、研究资料和企业内部文档，用户可以围绕资料提问、核对原文与图表，再通过工具和技能完成后续任务。

平台支持自行部署、接入模型 API，并按用户和部门管理访问范围。当前升级重点是 **PDF 图文检索、长文档入库稳定性以及智能体执行体验**。

## 核心能力

| 能力 | 使用方式 |
|---|---|
| **PDF 图文检索** | 保留符合规则的视觉页，将页码、图题、正文与页图关联，检索后查看对应页面 |
| **知识库与 RAG** | 文档解析、分块、向量与关键词检索、重排、来源引用和检索测试 |
| **智能体任务执行** | 组合模型、工具、Skills、MCP 与子智能体，执行多步骤任务 |
| **工作区与成果** | 管理任务文件，预览、下载智能体产物，继续处理已有资料 |
| **知识图谱** | 构建和浏览实体关系，结合文档检索探索关联内容 |
| **团队与模型管理** | 用户、部门、共享权限、模型供应商配置及运行数据查看 |

### PDF 图文资料：检索结果能回到具体页面

- 上传 PDF 时可启用“保留 PDF 视觉页”，关联正文、页码和图片资产。
- 对含图题、表题或内嵌图片的页面保留页图，普通文本页继续走文本解析。
- 可选视觉模型为页面补充描述，帮助检索云图、曲线、示意图等内容。
- 图片访问沿用知识库权限；解析或页图处理失败时报告错误，便于排查和重试。

当前检索以文本、图题及可选视觉描述为基础，并展示关联页图；不承诺原生以图搜图或识别所有无标题矢量图。实现边界见 [PDF 视觉页检索说明](docs/develop-guides/decisions/implemented/2026-08-30-multimodal-pdf-page-retrieval.md)。

### 从知识问答到任务交付

在聊天中使用 `@` 引入知识库、文件或技能。智能体按配置调用工具、检索资料和组织子任务，界面展示执行状态与工具结果；需要审批的操作由用户确认。生成的文件可在工作区预览、下载和继续编辑。

检索引用帮助核查答案，但不能保证回答始终正确；专业判断仍需结合原始资料复核。

## 技术架构

| 层次 | 主要组件 |
|---|---|
| 交互界面 | Vue 3、Vite、Ant Design Vue |
| API 与智能体 | FastAPI、LangGraph、Skills、MCP |
| 后台执行 | ARQ worker、Redis |
| 业务与文件存储 | PostgreSQL、MinIO |
| 检索与图谱 | Milvus、Neo4j |
| 文档处理 | PDF 解析、OCR、可选视觉模型 |
| 部署 | Docker Compose |

请求与运行状态由 PostgreSQL 持久化，后台 worker 执行任务，前端接收运行事件。详细模块职责与执行链路见 [架构说明](ARCHITECTURE.md)。

## 快速启动

准备 Docker、Docker Compose，以及可用的模型 API 凭据。知识库功能还需配置嵌入模型；OCR、视觉解析及其他扩展按需配置。

### 1. 获取升级版代码

```bash
git clone --branch feat/multimodal-pdf-retrieval https://github.com/viceleeland/Lingda-Pro.git
cd Lingda-Pro
```

`feat/multimodal-pdf-retrieval` 是当前升级版默认分支。历史版本标签用于保留版本来源，不代表包含全部升级改动。

### 2. 初始化配置

Linux / macOS：

```bash
./scripts/init.sh
```

Windows PowerShell：

```powershell
.\scripts\init.ps1
```

按脚本提示生成 `.env` 和安全密钥，并填写模型配置。配置项以 [.env.template](.env.template) 为准；实际密钥和运行数据不要提交到仓库。

### 3. 启动并检查

```bash
docker compose up --build -d
docker compose ps
```

打开 [就绪检查](http://localhost:5050/api/system/ready)，确认 `status` 为 `ready` 后访问：

- **应用**：[http://localhost:5173](http://localhost:5173)
- **API 文档**：[http://localhost:5050/docs](http://localhost:5050/docs)

首次访问按页面提示创建管理员。模型费用、依赖服务和硬件需求取决于实际配置。已有部署升级前，请先阅读 [部署与升级指南](docs/advanced/deployment.md)。

## 文档与反馈

- [模型配置](docs/intro/model-config.md)：接入聊天、嵌入和重排模型。
- [知识库使用](docs/intro/knowledge-base.md)：资料入库、检索与结果核对。
- [智能体配置](docs/agents/agents-config.md)：配置模型、工具与扩展能力。
- [知识库运维](docs/advanced/knowledge-base-operations.md)：排查文档处理与入库问题。
- [生产部署](docs/advanced/deployment.md)：服务部署、备份与升级。
- [反馈问题](https://github.com/viceleeland/Lingda-Pro/issues)：提交复现步骤、环境和脱敏日志。

## 开源致谢与许可

感谢 [Yuxi](https://github.com/xerrors/Yuxi) 及相关开源社区提供的基础工作，也感谢 LangGraph、Vue、FastAPI、Milvus 等项目。

本仓库遵循 [MIT License](LICENSE)，保留原有版权与许可声明。第三方组件遵循各自许可证。
