"""API v1 master router aggregating all domain sub-routes."""

from fastapi import APIRouter

from app.api.v1.routes import (
    agent,
    audit,
    decisions,
    demo,
    evaluations,
    health,
    mandates,
    memories,
    merchants,
    payments,
    policies,
    transactions,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(users.router)
api_router.include_router(merchants.router)
api_router.include_router(mandates.router)
api_router.include_router(policies.router)
api_router.include_router(transactions.router)
api_router.include_router(decisions.router)
api_router.include_router(payments.router)
api_router.include_router(memories.router)
api_router.include_router(audit.router)
api_router.include_router(evaluations.router)
api_router.include_router(agent.router)
api_router.include_router(demo.router)
