"""API routes package."""

from fastapi import APIRouter

from app.routes import (
    analytics,
    assistant,
    auth,
    dashboard,
    documents,
    explore,
    health,
    reports,
    reviews,
    search,
    system,
    topics,
    users,
    validation,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["Reviews"])
api_router.include_router(assistant.router, prefix="/assistant", tags=["AI Assistant"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(topics.router, prefix="/topics", tags=["Topics"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(validation.router, prefix="/validation", tags=["Validation"])
api_router.include_router(explore.router, prefix="/explore", tags=["Data Exploration"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(system.router, prefix="/system", tags=["System"])
