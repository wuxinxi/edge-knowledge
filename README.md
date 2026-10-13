# Edge Assistant

电脑本地助手，当前提供文档与图片检索、独立图片识字和按模型能力分流的问答。文档解析、切片、嵌入和检索在本机完成；生成回答时把问题、相关片段与有限的当前对话上下文发送至 DeepSeek。

基于 Electron + Vue 3 + TypeScript 与 FastAPI + EmbeddingGemma 2 + Chroma。架构按页面、通信、API、应用用例、领域、基础设施明确分层，产品定位见 [产品方向](docs/product.md)，分层实现见 [架构说明](docs/architecture.md) 与 [接口约定](docs/api.md)。

## 开始运行

需要 Node.js 22.12+、uv 与 Python 3.12。当前桌面开发启动针对 macOS。

```bash
npm ci
uv sync --project backend --extra embedding --extra ocr --group dev
npm run setup:model
npm run dev
```

Electron 会启动独立 Python 服务、自动配置认证与端口、打开桌面窗口。进入「我的知识库」导入资料，在「偏好设置」填入 DeepSeek API Key，然后开始问答。首次先准备检索模型，窗口启动不加载权重。模型未准备时，图片识字仍可独立使用。没有密钥时仍可导入与检索，生成回答需要有效密钥。

助手入口默认「查找资料」，只在本机检索；切换「资料问答」后才会使用 DeepSeek 组织回答。当前支持文档与 PNG、JPEG、WebP 图片。默认通过本地 OCR 文字回答；云端看图需要支持图片的模型及本次授权。详见 [图片工作流](docs/image-workflow.md)。

准备脚本默认把模型写入项目 `data/models/embeddinggemma-2/`。独立后端与桌面开发会自动发现；其他模型目录可通过 `EDGE_EMBEDDING_MODEL_PATH` 指定。推理只读取本地模型文件。应用生成阶段仍会调用 DeepSeek；这是混合本地检索方案。

## 浏览器开发

桌面方式无需 `.env`。如需独立调试后端和页面：

1. 复制 `.env.example` 为 `.env`，把 `EDGE_BACKEND_TOKEN` 替换成随机令牌。
2. 在项目根目录运行 `npm run dev:backend`。
3. 在另一个终端运行 `npm run dev:web`，打开 `http://127.0.0.1:5173`。

开发代理在服务端添加认证头，浏览器页面不需要令牌。浏览器模式与 Electron 使用不同的数据目录。`.env`、数据与模型不进入 Git。

## 项目结构

```text
apps/desktop/
├── electron/           # 窗口与 Python 子进程生命周期
└── src/
    ├── app/            # 应用入口、布局、全局状态
    ├── features/       # chat / library / settings 页面与特性状态
    └── shared/         # HTTP / SSE / 接口类型
backend/src/edge_knowledge/
├── domain/             # 纯领域实体、切片规则、业务错误
├── application/        # 用例与抽象端口
├── infrastructure/     # 模型、Chroma、文件解析、配置、DeepSeek 适配器
├── api/                # FastAPI 请求校验、认证、路由、SSE
└── bootstrap.py        # 唯一依赖组装点
backend/tests/          # 领域、架构约束、真实存储和接口集成测试
docs/                   # 架构与 API 约定
scripts/                # 后端打包准备
```

## 验证

```bash
npm run check
npm run build
```

后端测试使用实际 Chroma、Pillow 和可用时的 macOS Vision / RapidOCR 本地模型；跨平台 OCR 测试阻止网络连接后执行识别。嵌入与生成使用受控适配器，不下载模型、不使用真实密钥、不产生 DeepSeek 费用。桌面进程测试实际启动并终止 Python 服务。构建产物位于 `out/`。

需要验证实际模型时，安装嵌入依赖后运行 `uv run --project backend --no-sync python scripts/check_model.py`。此检查需要先准备模型权重，不调用 DeepSeek。

## 对话与快捷输入

- 侧栏按当前知识库显示对话，新建会话保留旧对话；更多操作支持重命名与删除，删除后可立即撤销。
- 输入 `@` 或 `/reference`（也支持 `/引用`）选择已入库资料，最多 10 份；引用后只检索所选文件的相关片段。
- `/search`、`/ask`、`/summarize`、`/new` 对应搜索、资料问答、总结与新建对话，支持中文别名；方向键选择、Enter 确认、Esc 关闭。
- 设置分为通用、模型、图片、检索、权限与隐私、数据与关于六个分区。界面偏好即时保存，连接设置通过「保存设置」提交当前分区。中英文切换保留资料原文、文件名和已有回答。
- 「多模态工作台」支持媒体查询、联合入库、分类聚类查重、JSON 结果导出；语义重复资料可暂存并恢复。
- 默认系统字体、13px 界面文字和 15px 对话正文；阅读字体可单独选择。全局配色、间距与主题规范见 [界面规范](docs/design-system.md)。

## macOS 打包准备

```bash
uv sync --project backend --extra embedding --extra ocr --extra packaging --group dev
uv run --project backend --no-sync python scripts/package_backend.py
npm run package:mac
```

后端采用 PyInstaller `onedir`，目录整体进入 Electron resources，避免大型模型运行库每次启动自解压。默认不把模型权重打进安装包；安装后需先准备模型至本机数据目录。发行前还需要验证 arm64/x64、代码签名和公证；当前提供的是打包配置，不代表已完成发行验证。

## 当前完整能力范围

提供知识库创建与切换、文档与图片导入、本地 OCR、图片预览、去重、删除、检索、来源片段、流式/非流式生成、停止回答及设置。对话在本机保存，支持新建、切换、重命名、删除、撤销及 Markdown 导出；每次问题重新检索，生成使用有限历史。设置支持系统/浅色/深色主题、配色、字体、字号、中英文和发送快捷键。另提供多模态工作台：图片查询、图文/多图联合编码、音视频检索与片段播放、任务分类、聚类、语义查重和可恢复暂存，以及 8K 上下文预算预检。完整使用与实现说明见 [多模态能力攻略](docs/multimodal-guide.md)。本地通用视觉描述、音视频转录与生成式总结、应用内模型下载管理、并行导入任务是独立的后续能力。系统凭据库、备份恢复和资料回收站已接入，见 [数据维护说明](docs/backup-and-credentials.md)。

原始 [开发指南](本地知识库助手开发指南.md) 保留作为需求参考；具体已实现边界以架构说明为准。

知识库页面可直接添加文件夹来源，支持子目录和每分钟增量同步、暂停/恢复、移除来源，以及相对路径清单搜索与分页。文件/目录只读授权与撤销仍在侧栏「本地权限」管理，见 [文件夹知识库](docs/folder-sources.md)。当前完成范围与未完成项见 [待办清单](docs/completion-gaps.md)。

设置 → 数据与关于可创建本机 `.edgebackup`，校验后恢复为新知识库；目录授权与 API Key 不进入备份。普通资料移除可在“回收站与暂存”恢复。系统密钥存储及旧配置迁移说明见数据维护文档。

## 跨平台图片文字识别

安装 `ocr` 依赖后，macOS 优先系统 Vision，Windows/Linux 使用本机 RapidOCR/ONNX Runtime。模型随依赖安装，识别时不下载、不上传；设置显示引擎与可用状态。Windows Python 子进程路径已适配，但 Windows/Linux 完整安装包及其他系统集成仍需实机验收。详见 [本地 OCR](docs/local-ocr.md)。

## 筛选、统计与 AI 规划

聊天中的“筛选与统计”支持组合日期、标签、类型、文字和自定义字段，并执行计数、数值聚合、分组与排序，不需要 API Key。复杂自然语言只有明确开启 AI 模式才允许 DeepSeek 规划；结果仍由本机执行。旧资料自动补建元数据索引，不重新生成向量。详见 [通用查询执行](docs/query-engine.md)。

### 本地生成模型

默认使用本地 GGUF 理解问题与依据资料回答，DeepSeek 可在设置中手动选择。进入“偏好设置 → 模型”，填写 GGUF 完整路径与 llama-server 路径，点击“保存并加载模型”。已有权重无需重新下载，已有知识库无需重建。本地失败不会自动转向云端。运行与能力边界见 [本地模型](docs/local-model.md)。
