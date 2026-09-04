from functools import lru_cache

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

    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "knowledge_units"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "akrag-neo4j"

    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_llm: str = "gpt-4o-mini"
    model_embedding: str = "text-embedding-3-small"
    model_rerank: str = "bge-reranker-v2-m3"
    embedding_dim: int = 1536

    default_tenant: str = "default"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def use_real_model(self) -> bool:
        return bool(self.model_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
