# Edge Knowledge development rules

- Keep `domain` independent of frameworks, storage, network, and filesystem.
- `application` may depend only on the domain, standard library, and its own ports.
- `api` may call use cases and ports; it must not import concrete infrastructure.
- Wire concrete dependencies only in `backend/src/edge_knowledge/bootstrap.py`.
- Renderer components call `shared/api/client.ts`; never call Electron/Node, Chroma, or DeepSeek directly.
- Put feature state and behavior in its feature directory. Shared types/transport must not depend on features.
- Desktop main owns process/window lifecycle. Preload exposes only narrow named operations.
- Never return, log, or commit the DeepSeek key. Never log retrieved document contents.
- Do not silently substitute synthetic embeddings for a missing production model.
- Document changes to layer boundaries in `docs/architecture.md`.
- Keep tests for dependency direction, data isolation, secret handling, and SSE boundaries passing.
- Verification: `npm run check`, `npm run build`. Install Python dependencies with `uv sync --project backend --extra embedding --extra ocr --group dev` first.

- Keep image OCR and cloud vision separate; cloud images require per-request consent and a model capability declaration.
- Never treat embedding vectors or filenames as visual evidence. Preserve source IDs, OCR status, and local asset isolation.

## 提交约定

- 每完成一个独立功能或修复，先完成对应验证，再立即提交，不积累多轮功能后统一提交。
- 每次提交只包含当前功能及其必要依赖；共享文件按相关改动拆分，避免混入无关功能。
- 提交标题和正文使用中文。提交前检查暂存区，保留尚未完成或不属于当前功能的改动。
