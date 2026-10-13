from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDGE_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    backend_token: str = ""
    port: int = 8765
    embedding_model: str = "google/embeddinggemma-2"
    model_offline: bool = False
    image_embeddings: bool = True
    embedding_model_path: Path | None = None
    prepared_model_dir: Path | None = None
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    renderer_origin: str = ""
    local_model_path: Path | None = None
    local_server_path: Path | None = None

    @field_validator("renderer_origin")
    @classmethod
    def local_renderer_only(cls, value: str) -> str:
        if value:
            url = urlparse(value)
            if (
                url.scheme != "http"
                or url.hostname not in {"127.0.0.1", "localhost"}
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("Renderer origin must be a local HTTP origin")
        return value
