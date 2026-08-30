# 文档处理与 OCR

Yuxi 把文档处理拆成两步：先把原文件保存到知识库，再根据文件类型和 OCR 配置生成 Markdown。知识库索引使用生成后的内容；附件解析只把结果写回当前 Workdir，不会创建知识库文件记录。

文件状态和存储归属见[知识库机制详解](../mechanisms/knowledge-base.md)，第一次上传文档见[创建并使用知识库](../intro/knowledge-base.md)。

## 支持的文件

知识库上传接口当前支持：

- 文本：`.txt`、`.md`、`.html`、`.htm`、`.json`、`.csv`；
- Office：`.docx`、`.pptx`、`.xls`、`.xlsx`；
- PDF：`.pdf`；
- 图片：`.jpg`、`.jpeg`、`.png`、`.bmp`、`.tiff`、`.tif`；
- ZIP：压缩包内必须包含 UTF-8 编码的 `.md` 文件。

图片文件必须使用 OCR 引擎。PDF 可以选择 OCR；选择 `disable` 时，系统会尝试直接读取 PDF 文本层，扫描版 PDF 通常得不到内容。

上传 PDF 时可以开启“保留 PDF 视觉页，支持图片检索”。系统把具有编号的 Figure、Fig.、Table、图、表题或内嵌图片（包括嵌套 Form XObject 中的栅格图片）的页面渲染为页图，保存到当前知识库的私有图片存储，并把原 PDF 页码、图题、图片链接和该页文字写入同一个 `## Page N` Markdown 段落。纯文本页不生成图片对象。带页图的 Markdown 按原页隔离分块，overlap 不会把相邻页图复制进同一结果。检索继续使用当前知识库的 embedding、BM25 和 reranker；命中视觉页时，查询结果会显示对应页图。该能力支持用文字查找图片，不等同于原生图片向量或以图搜图。

直接读取文本层时，页图和页面正文按页组织。启用页图后，RapidOCR、PP-Structure-V3、DeepSeek OCR 与 PP-OCRv6 等没有可持久图片资产的 OCR 会保留逐页输出边界，页图插入对应的 `## Page N` OCR 正文；仅在兼容没有页边界的结果时，才追加包含原页码和文本层正文的视觉页。DeepSeek Vision 的页图也会插回相同 `## Page N` 段落，与该页视觉描述共同索引。已经返回图片产物的 MinerU 和 PaddleOCR-VL 使用各自的图片链路，不重复生成页图。视觉页默认按 144 DPI 流式渲染，长文档的处理时间和私有图片存储占用会随视觉页数量增加。

启用页图后，单页渲染或上传失败会使本次解析进入 `error_parsing`，错误信息包含 `pdf_visual` 和失败页码，不会在缺图时静默标记为完整成功。排除存储或 PDF 问题后可以重试解析。

ZIP 处理会优先使用名为 `full.md` 的 Markdown 文件，否则使用压缩包中找到的第一个 `.md` 文件，并把 `images/` 下的图片上传到知识库图片存储。压缩包内的绝对路径和 `..` 路径会被拒绝。

## 从 URL 导入网页

网页导入受白名单控制。设置 `YUXI_URL_WHITELIST` 后，系统才会抓取 URL，并把 HTML 转成 Markdown 进入同一套知识库处理流程：

```bash
YUXI_URL_WHITELIST=github.com,docs.example.com,*.wikipedia.org
```

列表以逗号分隔；配置的域名及其子域名可以通过校验，空列表表示关闭 URL 导入。抓取器在 DNS 正常解析到 loopback、私有网段或 link-local 地址时会拒绝请求，并逐跳检查重定向目标；最多跟随 5 次重定向，只接受 HTML，响应体默认不超过 10 MB。DNS 解析失败目前会记录日志后继续请求，因此 URL 白名单和地址检查不能当作网络出口防火墙；生产环境还应在网络层限制出口。

## 选择 OCR 方案

| 引擎 | 运行位置 | 输出和适用场景 |
| --- | --- | --- |
| RapidOCR | 本地 CPU | 轻量图片/PDF 文字识别，默认方案 |
| MinerU | 本地 GPU 服务 | 复杂 PDF、表格和版面分析，输出 Markdown |
| MinerU Official | MinerU 云服务 | 不在本机部署 GPU，使用官方解析服务 |
| PP-Structure-V3 | 本地 GPU 服务 | 表格、票据和版面解析 |
| DeepSeek OCR | SiliconFlow API | 使用 SiliconFlow 的 DeepSeek OCR 模型 |
| DeepSeek 官方视觉 | DeepSeek API | 读取图片文字并描述云图、曲线、示意图与几何信息 |
| PaddleOCR-VL-1.6 | 百度 AI Studio 云服务 | 文档版面解析，输出 Markdown |
| PP-OCRv6 | 百度 AI Studio 云服务 | 基础 OCR，输出纯文本 |

系统内部引擎 ID 为 `rapid_ocr`、`mineru_ocr`、`mineru_official`、`pp_structure_v3_ocr`、`deepseek_ocr`、`deepseek_vision`、`paddleocr_vl_1_6` 和 `paddleocr_pp_ocrv6`。页面中的健康状态只表示配置或服务探测结果，真正解析时仍会验证凭证和接口。

## 在页面配置

管理员进入“设置 → OCR 配置”可以设置默认引擎，并配置自托管服务地址或云端凭证。知识库上传和附件解析时可以单独选择引擎；没有单独选择时，使用系统默认值。

配置字段的读取规则是：数据库中保存的非空值优先，数据库没有值时读取对应环境变量。保存为空会清除数据库值并回到环境变量。API 不会回显环境变量中的密钥；数据库凭证只显示脱敏预览。

## 配置各类引擎

### RapidOCR

RapidOCR 随 API/worker 安装，第一次实际解析时加载 ONNX 模型。默认模型目录由 `RAPIDOCR_MODEL_DIR` 指定；没有设置时使用容器缓存目录。它不需要单独启动服务，但首次解析可能需要下载模型。

### MinerU

开发 Compose 已提供 `mineru-api`，它属于 `all` profile，端口为 `30001`，解析端点是 `/file_parse`：

```bash
docker compose --profile all up -d --build mineru-api
```

API/worker 在 Compose 中默认使用 `MINERU_API_URI=http://mineru-api:30001`。如果显存不足导致 MinerU 启动失败，可以在 `docker-compose.yml` 的 `mineru-api.command` 中启用并调整：

```yaml
# --gpu-memory-utilization 0.5
```

该参数用于减小 vLLM KV cache；仍然不足时可以继续尝试 `0.4` 或更低值。模型下载和其余显存参数以 `docker/mineru.Dockerfile` 与 Compose 为准。解析超时可以用 `MINERU_TIMEOUT` 调整，或在单次处理参数中传入 `timeout_seconds`。

### MinerU Official

在[官方服务](https://mineru.net)申请 API Key，放入 API/worker 的环境：

```bash
MINERU_API_KEY=<your-mineru-api-key>
```

页面中配置也可以保存该凭证；生产环境优先使用环境变量。该服务会把文件发送到外部服务，请先确认数据合规和供应商条款。

### PP-Structure-V3

开发 Compose 的 `paddlex` 服务属于 `all` profile，默认在容器内的 `8080` 端口提供版面解析：

```bash
docker compose --profile all up -d --build paddlex
```

API/worker 默认使用 `PADDLEX_URI=http://paddlex:8080`。本地 GPU 和镜像构建要求以 Compose 为准。

### DeepSeek OCR

在“智能体 → 模型供应商”中启用 `siliconflow-cn` 并配置凭证。DeepSeek OCR 会复用该供应商的 API 地址和 API Key，不接受单独的 OCR 凭证配置。

### DeepSeek 官方视觉

在“智能体 → 模型供应商”中启用 `deepseek` 并通过 `DEEPSEEK_API_KEY` 配置凭证。该引擎调用 `deepseek-v4-flash-vision-exp`，除提取可见文字外，还会为图表、云图、示意图、颜色和几何关系生成简短描述。它使用 DeepSeek 官方账户的计费余额，与 SiliconFlow Key 和余额互不通用。

### PaddleOCR API

在[百度 AI Studio Access Token 页面](https://aistudio.baidu.com/account/accessToken)获取 Access Token：

```bash
PADDLEOCR_API_TOKEN=<your-paddleocr-token>
PADDLEOCR_API_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
```

`PADDLEOCR_API_URL` 可省略，默认使用上面的地址。`PaddleOCR-VL-1.6` 和 `PP-OCRv6` 共用这组配置；前者输出 Markdown，后者输出纯文本。

## 分块参数和配置快照

知识库的分块配置由两部分组成：`chunk_preset_id` 表示策略，`chunk_parser_config` 保存该策略的具体参数。文件级 `processing_params` 会保存本次使用的 `ocr_engine`、分块策略和参数快照；OCR 服务地址和凭证在执行时读取，不写入文件快照。

修改分块策略不会自动重写已经索引的文件。要让旧文件使用新策略，需要重新解析或重新入库，并在最后确认文件状态和检索结果。

## 图片访问

解析器生成的知识库图片保存在私有 `kb-images` bucket，通过带知识库权限校验的后端路径访问。PDF 页图对象使用 `{kb_id}/kb-images/{file_id}/pdf-pages/page_NNNN.png` 文件级稳定名称：重解析会覆盖同页对象，并在新 Markdown 保存后清理不再引用的页图；删除文件会清理整个文件级图片前缀。旧版本直接写在知识库根图片前缀下的时间戳对象没有文件归属，不能安全按文件自动清理，只能随整库删除或由运维确认后清理。不要把 MinIO 对象地址直接写成公开 URL，也不要为方便预览而开放整个 MinIO 管理端口。头像等公开图片使用 `/minio/public/...` 同源只读代理，二者边界不同。

## 文件限制与排查

- 知识库和工作区单个上传文件最大 100 MB。
- 工作区一次最多上传 50 个文件；知识库批量处理使用任务和页面限制。
- Agent 的 `read_file` 直接读取 UTF-8 文本和图片；PDF、Office 或其他二进制文件先用 `ocr_parse_file` 生成 Markdown。
- OCR 服务不可用时，先在 OCR 配置页查看健康状态，再检查容器日志、API 地址和凭证。
- 解析完成不等于索引完成；回到知识库文件列表确认 `parsed` 或 `indexed`，再做检索验证。

详细变量和容器映射见 `.env.template`、`docker-compose.yml` 和 `docker-compose.prod.yml`。文档页面只保留影响操作的配置，避免与配置文件维护两份默认值。
