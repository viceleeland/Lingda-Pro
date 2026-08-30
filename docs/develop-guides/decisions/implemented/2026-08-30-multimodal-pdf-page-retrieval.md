# PDF 视觉页检索

状态：implemented
类型：feature
Owner：backend/package/yuxi/knowledge/parser/unified.py

## 问题

PDF 的直接文本解析与纯文本 OCR 只把字符写入解析 Markdown。云图、曲线、网格和接触示意图没有可持久访问的图片资产，检索结果即使命中图题和周边文字，也不能向用户展示对应视觉页。对整份 PDF 逐页调用云端视觉模型会把有文本层的普通页面也转成外部请求，成本和时延随总页数增长。

知识库已经通过 MinIO 私有 bucket、鉴权图片代理、Markdown 图片链接和语义分块拥有图文存储与索引能力。缺失的行为属于 PDF 解析与查询结果展示，不需要新增向量 schema 或独立图片数据库。

## 决策

文件上传参数增加“保留 PDF 视觉页”选项，默认开启。PDF 解析器按页读取文本，只把具有编号的 Figure、Fig.、Table、图、表题或内嵌栅格图片（包括 Form XObject 内嵌套图片）的页面渲染为 PNG。单页渲染在调用 PDFium 前同时限制最大像素面积和单边尺寸，异常 MediaBox 自动等比降采样。页图使用 `{kb_id}/kb-images/{file_id}/pdf-pages/page_NNNN.png` 文件级稳定对象名写入私有 `kb-images` bucket，并把原 PDF 页码、图题、鉴权代理 URL 和该页正文写入同一个 `## Page N` Markdown 段落。纯文本页保留页码与正文，不生成图片对象。

OCR 选择器增加 `deepseek_vision`。该引擎从 `deepseek` 内置供应商解析 `DEEPSEEK_API_KEY` 和官方 API 地址，使用 `deepseek-v4-flash-vision-exp`。它直接读取普通页文本，只把同一套规则识别出的视觉页发送给 DeepSeek，生成可检索的云图、曲线、示意图、颜色和几何描述。DeepSeek 官方账户与 SiliconFlow 的凭证、模型和余额保持独立，`deepseek_ocr` 继续拥有 SiliconFlow 专用模型语义。

关闭 OCR 时，页级 Markdown 直接拥有页面正文。启用页图后，RapidOCR、PP-Structure-V3、DeepSeek OCR 和 PP-OCRv6 等不返回可持久图片资产的 OCR 引擎保留逐页输出边界，页图插入对应的 `## Page N` OCR 正文；兼容未提供页边界的结果时，才追加含原页码和文本层正文的视觉页段落。DeepSeek Vision 已返回 `## Page N` 和视觉描述时，页图同样插回该页面段落，不再建立成组图片区。MinerU 和 PaddleOCR-VL 已拥有图片产物链路，不重复追加页图。

Milvus 继续索引 Markdown 中的图题、页码和周边文字，并使用现有 embedding、BM25 与 reranker。带文件级页图 URL 的 Markdown 在分块前按 `## Page N` 隔离，overlap 不跨页复制相邻页图；每个页图只属于对应页面分块。图片资产继续由 MinIO 和知识库图片代理拥有访问控制。查询测试页使用现有 Markdown 渲染器显示命中的图片；本提案不改变检索 API 返回结构。

## 替代方案

- 渲染全部 PDF 页面：不会漏掉无图题的视觉页，但会对长文档产生大量重复页图和存储开销，因此只保留为内部 `all` 参数，不在本阶段的上传 UI 中暴露。
- 整本调用 DeepSeek OCR 或其他视觉模型：可以生成更丰富的视觉描述，但会产生逐页外部调用、费用和失败面，且当前文本层已经足以支撑多数正文检索，因此作为可选增强而不是图片持久化前提。
- 新增图片向量字段和跨模态 embedding：能够支持原生图文向量与以图搜图，但需要新的模型协议、Milvus schema 和迁移。本阶段的用户目标是文字检索并返回图片，现有文本向量可以闭合该链路。
- 仓库外预处理脚本：能快速处理单份文档，但不会成为上传入口的稳定能力，其他 PDF 仍然丢失图片，因此拒绝。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 开启选项后，含图题或内嵌图片的 PDF 页生成 PNG、鉴权 URL 和可搜索 Markdown | 只抽取文字，或图片对象与页码、图题脱节 | `unified.py` 与 MinIO 图片对象 | parser unit；真实知识库入库后回读 Markdown、MinIO 对象和检索结果 | 恢复不上传页图的实现后，视觉页断言失败 | 相关 parser/OCR/KB unit 130/130 passed；已有真实环境在改动前确认 11 个 PDF、242 个页图对象及 Figure 55/56 回读，改动后的真实重解析尚未执行 |
| 纯文本页不生成图片对象，普通中英文散文不误判，嵌套 Form 图片不漏判 | 所有页面都被渲染，或嵌套图片页没有页图 | `pdf_visual.py` 的视觉页判定 | `test_pdfreader_does_not_render_plain_text_page`、图题负控与嵌套 XObject probe | `Figure out`、`Table of contents`、`表明`、`图书馆` 不得命中 | Passed |
| 巨幅或异常 MediaBox 不会分配无界位图 | 合法 PDF 在 PDFium 渲染时耗尽 worker 内存 | `unified.py` 页图 scale 上限 | 像素面积、单边尺寸 pure unit | 50,000×50,000 points 与超长窄页必须降采样 | Passed |
| 无图片资产的 OCR 保留逐页正文并绑定同页页图；DeepSeek Vision 把页图与同页描述绑定 | 开启 OCR 后上传选项静默失效，扫描页图与 OCR 正文脱节，或多个页图组成无页码图片块 | 各 OCR 页边界、`parse_pdf` 与页级分块 | RapidOCR、PP-Structure-V3、DeepSeek OCR、PP-OCRv6 页边界 unit，同页绑定 unit、DeepSeek Vision unit、页图 overlap 负控 | 相邻页面的图片 URL 不得进入同一 chunk，也不得重复 | Passed |
| 页图渲染或上传失败不会被标记为完整解析成功 | 页面缺图但文件仍是 `parsed` | `pdf_visual` 异常与文件状态机 | parser failure unit 与知识库状态 unit | 模拟 MinIO 失败后必须为 `error_parsing`，错误中保留 `pdf_visual` 和页码 | Passed |
| 重解析和删除不会让当前文件的页图对象代际泄漏 | 每次重解析产生新对象；删文件后图片残留 | 文件级对象前缀与 KB 生命周期 | 稳定对象名、stale cleanup 和 delete prefix unit | 新 Markdown 不再引用的页图必须删除，当前引用必须保留 | Passed；旧版根级时间戳对象不具备 file owner，未自动迁移 |
| 未开启选项时直接文本解析行为保持不变 | 现有 PDF 无条件生成图片和页标题 | `pdfreader` | parser 回归与显式关闭 OCR unit | 关闭参数后出现图片 URL 时失败 | Passed |
| 查询结果以 Markdown 展示命中图片并保持窄屏可读 | 前端只显示 Markdown 源码或图片溢出结果卡片 | `web/src/components/QuerySection.vue` | Web 29 unit、lint、build 与 Chrome DOM/截图 | 将内容恢复为纯文本插值后，图片不可见 | Passed：页面加载鉴权 blob，`complete=true`、`naturalWidth=1224`、`naturalHeight=1584` |
| CalculiX 技术手册可通过图题或周边术语命中并展示对应页图 | 只有文本块、错误页图或越权图片 URL | 完整 Compose 入库与检索链路 | 真实 PDF、Milvus、MinIO、HTTP、Agent 工具和 Chrome UI | 不含对应图题的通用问题不得调用知识库 | Passed：Figure 55/56 命中 `file_00636c` 原手册第 89 页并原样展示；武汉问题工具调用为 0；匿名图片访问 401、登录页面加载成功 |

## 后果

图题和内嵌栅格图片启发式可能漏掉没有标题的纯矢量图，也可能把普通表格页识别为视觉页。内部 `all` 参数可用于诊断或一次性全页处理，上传 UI 暂不承诺该选择。页图会增加 MinIO 存储和首次解析时间，因此默认 DPI 受限，按页流式渲染；超大页面会为了内存安全降低分辨率，并且不改变原 PDF 对象。

图片代理 URL 是知识库权限边界的一部分。实现和验收必须通过真实 HTTP 回读确认未授权用户不能访问图片；Markdown 渲染成功不能替代权限证据。视觉页文字描述仍来自文本层或所选 OCR，引擎不能理解的颜色关系和几何语义不会被伪装成已具备原生跨模态向量能力。

启用页图后，页图是解析结果的一部分，而不是可静默丢失的装饰。任一视觉页渲染或上传失败都会抛出 `service_name=pdf_visual`、`status_code=page_image_failed` 的解析异常；知识库沿用现有状态机写入 `error_parsing` 和带页码的 `error_message`，重试后才可进入完整成功状态。

页图对象归当前文件所有。重解析覆盖相同页码的稳定对象，并在新 Markdown 保存后删除不再被引用的页图；删除文件会清理整个文件级图片前缀。旧版本直接写在 `{kb_id}/kb-images/` 下的时间戳页图没有文件归属信息，无法安全自动迁移或按文件删除，只能随整库删除或由运维确认后一次性清理。真实 DeepSeek/API 图片 integration 仍受测试凭证限制，本次未调用外部模型；已有 Chrome 尺寸与私有 bucket 证据只能作为兼容性基线，不能替代改动后的真实重解析验证。
