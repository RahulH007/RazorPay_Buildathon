"""
RecoverOS — FastAPI Application Entry Point
Autonomous AI Revenue Recovery Engine
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.websocket_manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Create all tables on startup
    Base.metadata.create_all(bind=engine)
    print("[OK] Database tables created")
    yield
    print("[STOP] RecoverOS shutting down")


app = FastAPI(
    title="RecoverOS API",
    description="Autonomous AI Revenue Recovery Engine — Razorpay Hackathon",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health Check ---
@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0", "service": "RecoverOS"}


# --- WebSocket Endpoint ---
@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; receive any client messages
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# --- Mount Route Modules ---
from app.routes import webhooks, batch, recovery, metrics, audit  # noqa: E402

app.include_router(webhooks.router, prefix="/api", tags=["Webhooks"])
app.include_router(batch.router, prefix="/api", tags=["Batch Simulation"])
app.include_router(recovery.router, prefix="/api", tags=["Recovery"])
app.include_router(metrics.router, prefix="/api", tags=["Metrics"])
app.include_router(audit.router, prefix="/api", tags=["Audit Trail"])
