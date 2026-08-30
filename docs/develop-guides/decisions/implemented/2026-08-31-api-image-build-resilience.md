# API 镜像构建韧性

状态：implemented
类型：process
Owner：docker/api.Dockerfile

## 问题

API 镜像包含 OCR、LibreOffice、字体和前端工具所需的系统依赖。首次构建受 apt 镜像、基础镜像仓库和 Python 包下载波动影响，失败后只能整段重来；Windows 工作区还可能把入口脚本写成 CRLF，导致容器启动失败。

## 决策

- 清华 apt 源为首选；`apt update` 使用严格错误模式，索引下载不完整或安装失败时切换 Debian 官方 HTTPS 源并完整重试，两个来源都失败则构建失败。
- apt 与 uv 使用 BuildKit cache；apt 只清理索引、不清空 cache mount 中的下载包，uv 继续使用 `--frozen`，缓存不得改变锁定依赖闭包。
- uv 下载超时显式放宽，链接模式固定为 copy，避免跨挂载硬链接告警和不稳定行为。
- 镜像构建时规范化入口脚本 CRLF，并继续以非 root 用户运行服务。
- 根构建上下文通过 `.dockerignore` 排除 `.env*`、本地 provider 凭据和 secret/nogit 文件，避免凭据发送给远端 builder。

## 替代方案

- 始终使用 Debian 官方源：来源单一，但大陆网络下的构建时间和成功率不可控。
- 只增加重试、不切换来源：实现更小，但镜像源故障时无法恢复。
- 维护多个镜像轮询或内部基础镜像：恢复面更强，但增加供应链、发布和长期维护成本。

## 后果

构建需要支持 `RUN --mount` 的 BuildKit，并可能在故障时从第二个 apt 域名下载相同 Debian 包。回退不会吞错，也不对 Python 锁文件降级。基础镜像元数据仍由 Docker Hub/GHCR 提供；它们不可达时，apt 回退无法解决构建失败。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 首选 update 或 install 失败都会进入官方源回退 | apt 将索引下载警告视为成功，继续使用旧缓存 | Dockerfile apt RUN | 将清华域名映射到 `127.0.0.1` 后执行本地基础镜像负向构建 | 首选源连接失败后必须出现回退提示，且最终 sources 指向 Debian 官方 HTTPS 源 | Passed（真实负向构建，官方源 update/install 完成） |
| 两个来源均失败时构建失败 | 回退吞错并产出不完整镜像 | 同上 | `set -e` 与无兜底的官方 update/install | 官方 install 失败不得继续 | Passed（结构检查） |
| frozen Python 依赖不因缓存改变 | 热缓存产生不同依赖闭包 | uv RUN | `uv sync --frozen` 与既有 API 镜像运行 | 移除 frozen 时决策失效 | Passed（装配检查） |
| apt 下载包可跨构建复用 | 同一 RUN 的 `apt-get clean` 清空 cache mount | Dockerfile apt RUN | cache mount 保留 `/var/cache/apt`，仅删除 `/var/lib/apt/lists` | 恢复 `apt-get clean` 时审查失败 | Passed（结构检查） |
| 本地凭据不进入构建上下文 | 远端 builder 收到 `.env` 或 provider key 文件 | `.dockerignore` | secret pattern 审查 | 删除 `.env*` / `api-.txt` 忽略规则时失败 | Passed（结构检查） |
| 当前 Dockerfile 可完整构建 | 基础镜像或命令不可用 | Docker/外部 registry | `docker buildx build --check` / compose build | registry 不可达必须显式失败 | Blocked by environment：Docker Hub 镜像代理 403、GHCR token 连接超时；Dockerfile 已成功解析到基础镜像元数据阶段 |
