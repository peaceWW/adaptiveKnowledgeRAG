from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api import api_router
from app.config import get_settings
from app.deps import AppStores
from app.model_gateway.gateway import ModelGateway
from app.observability.metrics import init_observability
from app.seed import seed_if_empty
from app.storage import db as storage_db
from app.storage.es_store import ElasticStore
from app.storage.minio_store import MinioStore
from app.storage.neo4j_store import Neo4jStore
from app.storage.qdrant_store import QdrantStore
import app.deps as deps


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_observability()
    await storage_db.init_db()
    stores = AppStores(
        gateway=ModelGateway(),
        qdrant=QdrantStore(),
        minio=MinioStore(),
        es=ElasticStore(),
        neo4j=Neo4jStore(),
    )
    await stores.es.ensure_index()
    deps.stores = stores
    async with storage_db.SessionLocal() as session:
        await seed_if_empty(session, stores.gateway, stores.qdrant, stores.es, stores.neo4j)
    yield
    await stores.es.close()
    stores.neo4j.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Adaptive Knowledge RAG", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")

    @app.get("/")
    async def root():
        return RedirectResponse(url="/docs")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
