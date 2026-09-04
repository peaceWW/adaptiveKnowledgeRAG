import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import AppStores
from app.model_gateway.gateway import ModelGateway
from app.seed import seed_all
from app.storage import db as storage_db
from app.storage.es_store import ElasticStore
from app.storage.minio_store import MinioStore
from app.storage.neo4j_store import Neo4jStore
from app.storage.qdrant_store import QdrantStore


async def main() -> None:
    await storage_db.init_db()
    stores = AppStores(
        gateway=ModelGateway(),
        qdrant=QdrantStore(),
        minio=MinioStore(),
        es=ElasticStore(),
        neo4j=Neo4jStore(),
    )
    await stores.es.ensure_index()
    async with storage_db.SessionLocal() as session:
        await seed_all(session, stores.gateway, stores.qdrant, stores.es, stores.neo4j)
    print("seed complete")


if __name__ == "__main__":
    asyncio.run(main())
