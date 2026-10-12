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
