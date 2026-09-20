<div align="center">

<img src="web/public/favicon.svg" width="72" height="72" alt="Lingda-Pro" />

# Lingda-Pro

**Knowledge retrieval and agent collaboration for professional documents**

PDF text and figures · Traceable sources · Multi-step tasks · Self-hosted deployment

[Quick start](#quick-start) · [Capabilities](#capabilities) · [Architecture](ARCHITECTURE.md) · [中文](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-0F766E)](LICENSE)
[![Deploy: Docker Compose](https://img.shields.io/badge/Deploy-Docker_Compose-2496ED)](docker-compose.yml)

</div>

---

Lingda-Pro brings document ingestion, knowledge retrieval, agent execution and file management into one workspace. It is designed for working with technical manuals, research materials and internal documentation: ask questions, inspect source text and figures, and use tools and skills to complete follow-up tasks.

The current upgrade focuses on **PDF page-image retrieval, long-document ingestion reliability and agent execution**. Teams can host the platform themselves, configure model APIs and manage access by user and department.

## Capabilities

| Capability | What it provides |
|---|---|
| PDF text and figures | Associate page numbers, captions and text with selected page images |
| Knowledge bases and RAG | Parsing, chunking, vector and keyword retrieval, reranking and citations |
| Agent execution | Models, tools, Skills, MCP and sub-agents for multi-step tasks |
| Workspace and artifacts | File management, previews, downloads and continued work on generated files |
| Knowledge graphs | Entity-relation exploration alongside document retrieval |
| Team management | User and department permissions, model providers and runtime information |

### PDF retrieval with source pages

The optional page-preservation pipeline retains images for pages detected through figure/table captions or embedded raster images. Plain-text pages retain their text. A configured vision model can add searchable descriptions; page images remain protected by knowledge-base access controls.

Retrieval uses text, captions and optional visual descriptions to return associated page images. This is not native image-to-image vector search, and detection may miss untitled vector figures. See the [implementation and limitations](docs/develop-guides/decisions/implemented/2026-08-30-multimodal-pdf-page-retrieval.md).

### From questions to deliverables

Use `@` in chat to reference knowledge bases, files or skills. Agents can retrieve evidence, call tools and coordinate sub-tasks. The interface displays execution state and tool results, requests configured approvals, and provides previews and downloads for generated artifacts. Citations support verification; they do not guarantee a correct answer.

## Technology

| Layer | Components |
|---|---|
| Frontend | Vue 3, Vite, Ant Design Vue |
| API and agents | FastAPI, LangGraph, Skills, MCP |
| Background execution | ARQ worker, Redis |
| Business and file storage | PostgreSQL, MinIO |
| Retrieval and graphs | Milvus, Neo4j |
| Document processing | PDF parsing, OCR and optional vision models |
| Deployment | Docker Compose |

See [ARCHITECTURE.md](ARCHITECTURE.md) for module boundaries and execution flow.

## Quick start

Install Docker and Docker Compose, and prepare model API credentials. Knowledge retrieval requires an embedding model; OCR and vision integrations require their own configuration.

### 1. Clone the upgrade branch

```bash
git clone --branch feat/multimodal-pdf-retrieval https://github.com/viceleeland/Lingda-Pro.git
cd Lingda-Pro
```

The current default branch is `feat/multimodal-pdf-retrieval`. Historical tags preserve earlier versions and may not include the upgrade changes.

### 2. Initialize

Linux / macOS:

```bash
./scripts/init.sh
```

Windows PowerShell:

```powershell
.\scripts\init.ps1
```

Follow the prompts to create `.env`, generate security secrets and configure models. Refer to [.env.template](.env.template) for configuration keys. Do not commit credentials or runtime data.

### 3. Start

```bash
docker compose up --build -d
docker compose ps
```

Check [readiness](http://localhost:5050/api/system/ready). When `status` is `ready`, open:

- **Application:** [http://localhost:5173](http://localhost:5173)
- **API documentation:** [http://localhost:5050/docs](http://localhost:5050/docs)

Create the initial administrator through the first-run screen. Hardware requirements, external dependencies and model charges depend on configuration. Existing installations must follow the [deployment and upgrade guide](docs/advanced/deployment.md).

## Documentation and feedback

The implementation guides are currently in Chinese.

- [Model configuration](docs/intro/model-config.md)
- [Knowledge bases](docs/intro/knowledge-base.md)
- [Agent configuration](docs/agents/agents-config.md)
- [Knowledge-base operations](docs/advanced/knowledge-base-operations.md)
- [Deployment](docs/advanced/deployment.md)
- [Report an issue](https://github.com/viceleeland/Lingda-Pro/issues)

## Acknowledgments and license

Thanks to [Yuxi](https://github.com/xerrors/Yuxi) and its community for the foundational work, and to projects including LangGraph, Vue, FastAPI and Milvus.

This repository uses the [MIT License](LICENSE) and retains existing copyright and license notices. Third-party components retain their respective licenses.
