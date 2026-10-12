"""Populate a separate local demo library, never alter the user's existing corpus."""

import json
from pathlib import Path

import httpx
from edge_knowledge.infrastructure.config import RuntimeConfig

config = RuntimeConfig()
fixtures = Path(__file__).resolve().parents[1] / "backend/tests/fixtures"
with httpx.Client(
    base_url=f"http://127.0.0.1:{config.port}",
    headers={"Authorization": "Bearer " + config.backend_token},
    timeout=600,
) as client:
    client.get("/api/health").raise_for_status()
    libraries = client.get("/api/libraries").json()
    library = next(
        (item for item in libraries if item["name"] == "多模态验收资料"), None
    )
    if not library:
        response = client.post("/api/libraries", json={"name": "多模态验收资料"})
        response.raise_for_status()
        library = response.json()
    library_id = library["id"]
    for name, data in [
        (
            "architecture.txt",
            b"Local computer architecture uses a Python service for indexing documents and images.",
        ),
        (
            "architecture-copy.txt",
            b"Local computer architecture uses a Python service for indexing documents and images.",
        ),
        (
            "recipe.txt",
            b"Cooking recipe: chop tomatoes, scramble eggs, then stir fry them together.",
        ),
        *[
            (name, (fixtures / name).read_bytes())
            for name in ["parcel-demo.png", "speech-demo.wav", "video-demo.mp4"]
        ],
    ]:
        response = client.post(
            f"/api/libraries/{library_id}/documents", files={"file": (name, data)}
        )
        response.raise_for_status()
        print("Indexed", name, flush=True)
    image = (fixtures / "parcel-demo.png").read_bytes()
    response = client.post(
        "/api/multimodal/ingest",
        data={
            "options": json.dumps(
                {
                    "library_id": library_id,
                    "name": "图文与双图联合演示",
                    "text": "A delivery note with pickup code 6583, shown in two related images.",
                }
            )
        },
        files=[("files", ("front.png", image)), ("files", ("detail.png", image))],
    )
    response.raise_for_status()
    print(
        json.dumps(
            {"library_id": library_id, "name": library["name"], "items": 7},
            ensure_ascii=False,
        ),
        flush=True,
    )
