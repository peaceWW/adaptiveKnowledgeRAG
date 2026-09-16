from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),
    )

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str = "postgresql+asyncpg://akrag:akrag@localhost:5432/akrag"
    redis_url: str = "redis://localhost:6379/0"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "knowledge_units"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "akrag"
    minio_secure: bool = False
    # 本地持久目录：无 MinIO 时也把原文和截图写到磁盘，避免重启后文件丢失
    storage_dir: str = "data/storage"

    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "knowledge_units"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "akrag-neo4j"

    # 无 .env 时保持 OpenAI 兼容默认，避免本地演示被绑死在千问；千问配置见 .env.example
    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_llm: str = "gpt-4o-mini"
    model_vision: str = ""
    model_embedding: str = "text-embedding-3-small"
    model_rerank: str = "bge-reranker-v2-m3"
    embedding_dim: int = 1536
    # 千问 compatible-mode embedding 单次最多 10 条；OpenAI 可在 .env 调大
    embedding_batch_size: int = 10

    default_tenant: str = "default"
    cors_origins: str = "*"

    @property
    def storage_root(self) -> Path:
        """原文与截图落盘根目录；相对路径相对仓库根，避免启动目录变化后找不到文件。"""
        path = Path(self.storage_dir).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        return path.resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        items = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        return items or ["*"]

    @property
    def use_real_model(self) -> bool:
        return bool(self.model_api_key)

    @property
    def vision_model(self) -> str:
        """图/公式 Vision 调用：单独配 VL 模型，否则与文本 LLM 共用。"""
        return self.model_vision or self.model_llm


@lru_cache
def get_settings() -> Settings:
    return Settings()
