from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.dashboard import router as dashboard_router
from app.api.documents import router as documents_router
from app.api.evaluation import router as evaluation_router
from app.api.graph import router as graph_router
from app.api.kb import router as kb_router
from app.api.prompts import router as prompts_router
from app.api.retrieval import router as retrieval_router
from app.api.strategies import router as strategies_router
from app.api.units import router as units_router

api_router = APIRouter()
api_router.include_router(dashboard_router)
api_router.include_router(kb_router)
api_router.include_router(documents_router)
api_router.include_router(units_router)
api_router.include_router(strategies_router)
api_router.include_router(chat_router)
api_router.include_router(prompts_router)
api_router.include_router(retrieval_router)
api_router.include_router(evaluation_router)
api_router.include_router(graph_router)
api_router.include_router(admin_router)
