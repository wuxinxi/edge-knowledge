# 本地 API 约定

所有路由以 `/api` 开头，需要 `Authorization: Bearer <会话令牌>`。Electron 自动管理令牌；独立开发使用 `.env` 中的 `EDGE_BACKEND_TOKEN`。未授权返回 401；不存在的知识库/文档返回 404；输入校验失败返回 422。业务错误统一为 `{ "error": { "code": "…", "message": "…" } }`，不回显密钥或请求内容。

| 方法与路径                                              | 请求                                                                                     | 响应                                                                                   |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| GET `/health`                                           | 无                                                                                       | `{status, embedding_loaded}`                                                           |
| GET `/capabilities`                                     | 可选查询 `model`                                                                         | 嵌入模型就绪状态、视觉开关、指定生成模型图片能力、OCR 可用状态、当前图片模式与图片预算 |
| GET `/libraries`                                        | 无                                                                                       | `[{id, name, chunks}]`                                                                 |
| POST `/libraries`                                       | `{name}`                                                                                 | 新知识库，201                                                                          |
| GET `/libraries/{id}/documents`                         | 无                                                                                       | `Document[]`                                                                           |
| POST `/libraries/{id}/documents`                        | multipart 字段 `file`                                                                    | `{document, duplicate}`，201                                                           |
| DELETE `/libraries/{id}/documents/{document_id}`        | 无                                                                                       | `{deleted: true}`                                                                      |
| GET `/libraries/{id}/documents/{document_id}/thumbnail` | 无                                                                                       | PNG 缩略图，认证且按知识库隔离                                                         |
| GET `/libraries/{id}/documents/{document_id}/image`     | 无                                                                                       | 规范化 PNG，认证且按知识库隔离                                                         |
| POST `/ocr`                                             | multipart 字段 `file`                                                                    | `{status, text, regions, message, width, height}`                                      |
| GET `/settings`                                         | 无                                                                                       | 用户设置与 `api_key_configured`，从不返回密钥                                          |
| PATCH `/settings`                                       | 设置的部分字段                                                                           | 保存后的公开设置                                                                       |
| POST `/search`                                          | `{question, library_id?, top_k?, document_ids?}`                                         | `SearchHit[]`，不调用 DeepSeek                                                         |
| POST `/query`                                           | `{question, library_id?, top_k?, stream?, allow_image_upload?, document_ids?, history?}` | SSE，传输格式始终为 SSE                                                                |

`library_id` 默认 `default`；问题长度 1–4000 字符；`top_k` 1–20。`stream` 控制 DeepSeek 是否流式生成，非流式生成仍在 SSE 中发出一个完整的 delta。

`Document` 包括 `id, filename, chunks, size, created_at, kind, media_type, width, height, ocr_status, ocr_message, duration, assets`。`kind` 为 `document`、`image`、`audio`、`video` 或 `bundle`；文本宽高为 0。`SearchHit` 包括 `document_id, filename, text, section, index, score, kind, ocr_status, start, end`。图片命中按文档去重。

`capabilities` 的结构：

```json
{
  "embedding": {
    "ready": false,
    "images": true,
    "audio": true,
    "video": true,
    "joint": true,
    "context_limit": 8192,
    "dimensions": [128, 256, 512, 768]
  },
  "generator": { "model": "deepseek-flash", "images": true },
  "ocr": { "available": true },
  "image_qa_mode": "local_ocr",
  "max_cloud_images": 3
}
```

图片 OCR 状态为 `ready`、`empty`、`unavailable`、`error`；普通文档为 `not_applicable`。`regions` 包含 `text, confidence, bbox`，`bbox` 是已修正方向图片上以左上角为原点的归一化 `[x, y, width, height]`。独立识字不加载嵌入、不入库、不调用生成服务。

## SSE 与图片授权

```text
data: {"type":"sources","sources":[{"document_id":"…","filename":"ticket.png","text":"取件码 6583","section":"图片文字","index":1,"score":0.85,"kind":"image","ocr_status":"ready"}]}

data: {"type":"notice","message":"图片依据来自本地 OCR 文字，未向 DeepSeek 发送图片。"}

data: {"type":"delta","delta":"回答片段"}

data: {"type":"done"}

```

来源数组顺序对应提示词中的 `[1]`、`[2]`。`notice` 按需发送，说明证据类型和图片发送情况。没有相关资料或图片没有可用文字时可本地返回提示，不调用生成服务。生成失败发送 `error` 并结束流，不再发送 done。没有收到 done/error 就断开视为异常中断；停止生成会取消 HTTP 请求。

`allow_image_upload` 默认 false，仅对本次请求有效。设置为 `cloud_vision` 且命中图片时，模型须声明图片能力，调用方须明确传 true；否则返回 409（`image_model_unsupported` 或 `image_upload_required`）。最多发送 3 张相关图片，其余图片保留在来源列表供查看，但不参与回答。授权检查发生在附图读取与云端调用前。SSE 不包含图片字节、base64 或密钥。

## 设置

- `api_key` 省略表示保留，空字符串表示移除；服务端不会把密钥回传。
- `base_url` 仅允许官方 DeepSeek HTTPS 地址及其 `/v1` 地址。
- 新设置的 `model` 默认 `deepseek-flash`；已有模型名不强制迁移，未知模型不默认声明视觉能力。
- `image_qa_mode` 为 `local_ocr`（默认）或 `cloud_vision`。选择模式不替代逐次图片发送授权。
- `stream` 默认 true；`top_k` 默认 5；`min_score` 默认 0.2。
- `chunk_size` 100–4000 字符，默认 800；`chunk_overlap` 0–1000，默认 100，且小于切片长度。

## 文件与模型

支持 TXT、MD、PDF、DOCX、PNG、JPG/JPEG、WebP，每份不超过 20 MB。文本优先 UTF-8，失败后尝试 GB18030。PDF 只提取文字层，尚未支持扫描 PDF OCR。静态图片校验真实格式、像素上限并移除元数据；不支持动画图片。

文本原文件不保留，片段持久化在本机索引；图片保留规范化 PNG、缩略图与 OCR 区域。图片响应包含 `Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`。

导入和非空库语义检索需要已准备的本地嵌入权重。模型未就绪返回 503 `model_not_ready`，不在请求内下载；独立 OCR 仍可用。

## 指定资料与对话上下文

`document_ids` 默认为空（全库），最多 10 个有效的文档 ID；非空时只检索这些资料。每个 ID 须存在于当前知识库，删除或跨库引用返回 404 `reference_not_found`，不会默默退回全库。

`history` 默认为空，由当前会话的文字消息组成，角色只能为 `user` 或 `assistant`。最多 10 条，每条 1–6000 字符，总计不超过 24000 字符；不接受系统角色。生成使用这段上下文理解追问，来源编号只对应本次检索资料。历史不携带图片字节、密钥或持续图片发送授权。

## 多模态与资料整理

| 方法与路径                                                  | 请求                                                                            | 响应                                                                  |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| POST `/multimodal/budget`                                   | multipart `options` JSON 字符串与可选多个 `files`                               | `{limit,max_tokens,segments,fits,details}`；只解码/计数，不推理或入库 |
| POST `/multimodal/search`                                   | 同上                                                                            | `{sources,budget,dimension,aggregation}`                              |
| POST `/multimodal/ingest`                                   | 同上                                                                            | `{document,duplicate,budget?}`，201                                   |
| POST `/organize`                                            | JSON `{library_id?,task,document_ids?,dimension?,labels?,clusters?,threshold?}` | 分类 assignments、聚类 groups 或查重 pairs，以及参与 documents        |
| GET `/libraries/{id}/documents/{document_id}/media`         | 无                                                                              | 素材元数据列表，包含 index/filename/kind/media_type                   |
| GET `/libraries/{id}/documents/{document_id}/media/{index}` | 无                                                                              | 认证后的本地素材字节，no-store/nosniff                                |
| GET `/libraries/{id}/archive`                               | 无                                                                              | 当前库的可恢复暂存资料                                                |
| POST `/libraries/{id}/documents/{document_id}/archive`      | 无                                                                              | 从检索索引移出，保留原件和索引快照                                    |
| POST `/libraries/{id}/archive/{document_id}/restore`        | 无                                                                              | 重新写入索引快照，并移除暂存记录                                      |

`options` 包含 `library_id`（默认 default）、`text`（最多 32000 字符）、`name`、`task`（search/document/code/qa/fact）、`dimension`（128/256/512/768）、`top_k`（1–50）、`document_ids`（最多 200）和 `kinds`。纯媒体可以省略文字；纯文本可以省略文件。联合入库固定保留完整 768 维索引，检索时同维度截取并再次归一化。`aggregation` 为 joint 或 mean_of_segments，后者表示长查询分段取均值。

整理 `task` 为 classification/clustering/similarity；标签最多 30 个、每个最多 200 字符；期望聚类数 1–20；阈值 -1–1。查重 `pairs` 具有 left/right/score/exact，其中 exact 是规范化/解析后索引内容指纹相同，不等同于每一种原始容器文件的字节完全相同。一次整理最多 200 份文档；多模态精确检索最多 10000 个片段。

音视频通过普通资料导入路由也可入库：每份最多 200 MB、60 分钟；普通文档/图片仍为 20 MB。多模态组合最多 12 个文件、总计 240 MB，并最多一个音视频。详见 [多模态攻略](multimodal-guide.md)。超出 8K 的图文组合返回 413 `context_budget_exceeded`，纯文本或长媒体自动分段。媒体命中的 start/end 使用秒，保留可定位来源；空 text 不表示已生成转录。

原件、快照、任务范围与恢复均按知识库隔离。暂存后素材端点拒绝访问，恢复后重新可用。浏览器取消请求只停止等待，已经开始的本地事务仍会安全结束；不承诺底层模型前向中途取消。

## 数据备份

所有接口仍需本地会话认证。

- `POST /api/backup/export`：JSON `{chats?, preferences?}`，前端数据最多 3 MB。返回未加密 ZIP，`Cache-Control: no-store`，不包含凭据、服务配置、目录授权和模型权重。
- `POST /api/backup/inspect`：multipart `file`，最多 512 MB。返回 `model`、`compatible`、`libraries`、`documents`、`archived`、`missing_originals` 与校验后的 `frontend`；不会写入知识库。
- `POST /api/backup/restore`：multipart `file`。完整校验后恢复为新知识库，返回新 `libraries`、旧到新库 ID 的 `mapping` 与 `frontend`。不替换现有库。格式错误 `422 invalid_backup`，模型不一致 `409 backup_model_mismatch`，体积超限 `413`。

设置读取另返回 `credential_storage`、`credential_message`、`credential_migration_pending`。旧明文迁移失败时设置变更被明确阻止，重新保存密钥可以重试；系统凭据不可用为 `503 credential_unavailable`。

## 文件夹来源

本机目录的原生授权与扫描由 Electron 窄 IPC 执行；后端不接受绝对目录作为读取请求，仅接收已读字节和来源归属。以下接口仍需同一个本地会话令牌。

- `GET /api/libraries/{id}/folders/{source}/files`：来源 UUID 与知识库校验后返回 `{path, fingerprint, document_id}` 清单。
- `POST /api/libraries/{id}/folders/{source}/files`：multipart `path`（有效相对路径，最多 1024 字符）及 `file`。内容摘要未变跳过；新内容先成功索引再归档旧版本，返回 `{changed, document_id}`。文档/图片限制 20 MB，媒体沿用 200 MB 限制。
- `POST /api/libraries/{id}/folders/{source}/reconcile`：JSON `{paths: string[], complete: true}`，清单最多 6 MB / 10000 个唯一路径。宿主只有在完整扫描且所有文件处理成功时调用；不完整声明拒绝。只归档本来源缺失资料，不影响手动导入或其他来源，返回 `{removed}`。

来源目录绑定保存在 Electron 的私有 `folder-sources.json`，只读位置仍保存在 `local-access.json`；逐文件台账保存在后端按模型隔离的 SQLite。暂停/移除来源与撤销授权均不删除用户原件。完整使用与失败边界见 [文件夹来源](folder-sources.md)。

## 批量回收与目录同步代次

- POST `/libraries/{id}/documents/archive-batch`：`{document_ids: string[], all_documents: boolean}`，两种范围不能混用。ID 必须唯一且属于当前库；全库操作传空数组与 `all_documents: true`。返回 `{archived, document_ids, folder_sync_paused}`。最多 10000 份资料，普通失败尝试恢复原活动索引及原暂存快照。
- POST `/libraries/{id}/archive/restore-batch`：`{document_ids: string[], all_documents: false}`，也可省略 false。返回 `{restored}`。从保存的快照恢复，已恢复 ID 可重复提交。
- GET `/libraries/{id}/folders/{source}/lease`：返回 `{epoch, enabled}`，宿主扫描前取得代次。
- POST `/libraries/{id}/folders/{source}/activate`：显式连接、恢复或手动同步启用当前代次。
- 文件夹上传 multipart 与 reconcile JSON 加入 `epoch`，非负整数；旧客户端默认 0。清空增加持久化代次并禁用来源，旧代次上传/核对返回 409 `folder_sync_paused`。恢复资料不自动恢复目录同步。

应用客户端与宿主需要使用同一版本；旧开发服务需要重启才能加载新增接口。

## 聊天文本检索结果

`/search` 与 `/query` 的文本检索统一应用 `min_score`，top-k 为最多返回条数；不足时不补低质量片段。具体实体/编号与词项参与候选排序，输出 `score` 仍为余弦相似度，排序可能不按该单项分数递减。独立的新问题不拼接旧主题，明确短追问保留历史检索上下文。联合媒体 `/multimodal/search` 仍采用多模态策略。
