"""
RecoverOS — FastAPI Application Entry Point
Autonomous AI Revenue Recovery Engine

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app import ledger, __about__
from app.database import engine, Base, SessionLocal
from app.models import install_append_only_triggers
from app.websocket_manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Create all tables on startup
    Base.metadata.create_all(bind=engine)
    print("[OK] Database tables created")

    # Append-only triggers at the database level, so the ledger guarantee
    # survives someone opening the .db file directly rather than using the ORM.
    if install_append_only_triggers(engine):
        print("[OK] Ledger append-only triggers installed")

    # Report chain state at boot so a corrupted ledger is noticed immediately
    # rather than at demo time.
    db = SessionLocal()
    try:
        result = ledger.verify_chain(db)
        if result.valid:
            head = (result.head_hash or "-")[:16]
            print(f"[OK] Ledger verified: {result.entries_checked} entries, head {head}...")
        else:
            print(f"[FAIL] LEDGER VERIFICATION FAILED: {result.reason}")
    finally:
        db.close()

    yield
    print("[STOP] RecoverOS shutting down")


app = FastAPI(
    title="RecoverOS API",
    description=(
        "Revenue recovery with a tamper-evident audit trail.\n\n"
        f"{__about__.NOTICE}"
    ),
    version=__about__.VERSION,
    contact={"name": __about__.AUTHOR, "url": __about__.AUTHOR_GITHUB_URL},
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
    return {
        "status": "ok",
        "service": __about__.PROJECT,
        "version": __about__.VERSION,
        # Attribution travels with the API itself, so a deployed copy still
        # names its author even when the repository is not in view.
        "author": __about__.AUTHOR,
        "github": __about__.AUTHOR_GITHUB,
    }


@app.get("/")
async def root():
    """Project identity. Deliberately the first thing the API says."""
    return __about__.as_dict()


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
from app.routes import webhooks, batch, recovery, metrics, audit, llm  # noqa: E402
from app.routes import ledger as ledger_routes  # noqa: E402

app.include_router(webhooks.router, prefix="/api", tags=["Webhooks"])
app.include_router(batch.router, prefix="/api", tags=["Batch Simulation"])
app.include_router(recovery.router, prefix="/api", tags=["Recovery"])
app.include_router(metrics.router, prefix="/api", tags=["Metrics"])
app.include_router(audit.router, prefix="/api", tags=["Audit Trail"])
app.include_router(ledger_routes.router, prefix="/api", tags=["Ledger"])
app.include_router(llm.router, prefix="/api", tags=["LLM Activity"])
