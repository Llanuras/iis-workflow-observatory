import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .services import config
from .engine import Engine

engine = Engine()

@asynccontextmanager
async def lifespan(app):
    engine.store.recover()
    yield
    for task in engine.workers.values():
        if not task.done():
            task.cancel()

app = FastAPI(title="Workflow Observatory", lifespan=lifespan)

# Local application: reject browser requests from unrelated origins.
@app.middleware("http")
async def local_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin not in {"http://127.0.0.1:8000", "http://127.0.0.1:5173", "http://localhost:5173", "http://localhost:8000"}:
        return Response("Unrecognised origin", status_code=403)
    return await call_next(request)

@app.exception_handler(KeyError)
async def missing(request, exc):
    return Response('Task not found', status_code=404)

@app.exception_handler(ValueError)
async def invalid(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=409)

class Create(BaseModel):
    goal: str = Field(min_length=10, max_length=3000)

class Edit(BaseModel):
    version: int
    plan: dict | None = None
    instruction: str | None = Field(default=None, max_length=2000)
    redo: str | None = None
    revision: dict | None = None

class Apply(BaseModel):
    proposal_id: str


@app.get("/api/health")
def health():
    return {"status": "ok", "execution": "live", **config()}

@app.get("/api/tasks")
def tasks():
    return [{k: t[k] for k in ("id", "goal", "status", "version", "updated")} for t in engine.store.list()]

@app.post("/api/tasks", status_code=201)
async def create(body: Create):
    task = engine.create(body.goal.strip())
    engine.spawn(task["id"], engine.plan)
    return task

@app.get("/api/tasks/{tid}")
def get_task(tid: str):
    return engine.store.get(tid)

@app.post("/api/tasks/{tid}/plan")
async def replan(tid: str):
    async with engine.lock(tid):
        task = engine.store.get(tid)
        if task["plan"]:
            raise ValueError("Use workflow editing to revise an existing plan.")
        if tid in engine.workers and not engine.workers[tid].done():
            raise ValueError("Planning is already in progress.")
        task.update(status="planning", error=None)
        engine.store.save(task, "planning_retried", {})
        engine.spawn(tid, engine.plan)
    return task

@app.post("/api/tasks/{tid}/start")
async def start(tid: str):
    async with engine.lock(tid):
        task = engine.store.get(tid)
        if task["status"] not in {"ready", "paused", "needs_help"} or not task["plan"]:
            raise ValueError("A ready or paused plan is required.")
        if tid in engine.workers and not engine.workers[tid].done():
            raise ValueError("The previous operation is finishing. Try again shortly.")
        for sid, state in task["states"].items():
            if state in {"failed", "running"}:
                task["states"][sid] = "pending"
        # A reviewed evidence failure requires an explicit correction, rather than bypassing review.
        if all(v == "completed" for v in task["states"].values()):
            raise ValueError("All steps are complete. Preview a redo or revise an upstream result.")
        reviews = [r for sid,r in task["results"].items() if next(s for s in task["plan"]["steps"] if s["id"] == sid)["kind"] == "review"]
        if reviews and reviews[-1]["output"].get("sufficient") is False and task["automatic_repairs"] >= 1 and not any(s["kind"] in {"research", "review"} and task["states"][s["id"]] == "pending" for s in task["plan"]["steps"]):
            raise ValueError("Evidence remains insufficient. Revise or redo the review/research before continuing.")
        task.update(status="running", error=None)
        engine.store.save(task, "started", {"version": task["version"]})
        engine.spawn(tid, engine.run)
    return task

@app.post("/api/tasks/{tid}/pause")
async def pause(tid: str):
    async with engine.lock(tid):
        task = engine.store.get(tid)
        if task["status"] != "running":
            raise ValueError("Only a running task can be paused.")
        task["status"] = "pause_requested"
        engine.store.save(task, "pause_requested", {"message": "The current call will finish before pausing."})
    return task

@app.post("/api/tasks/{tid}/preview")
async def preview(tid: str, body: Edit):
    return await engine.preview(tid, **body.model_dump())

@app.post("/api/tasks/{tid}/apply")
async def apply(tid: str, body: Apply):
    return await engine.apply(tid, body.proposal_id)

@app.get("/api/tasks/{tid}/events")
async def events(tid: str, request: Request, after: int = 0):
    engine.store.get(tid)
    cursor = max(after, int(request.headers.get("last-event-id", "0") or "0"))
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            rows = engine.store.events(tid, cursor)
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\ndata: {json.dumps(row)}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.8)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

@app.get("/api/tasks/{tid}/download/{format}")
def download(tid: str, format: str):
    task = engine.store.get(tid)
    if format == "json":
        data = {"task": task, "events": engine.store.events(tid)}
        return Response(json.dumps(data, indent=2, ensure_ascii=False), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="workflow-{tid}.json"'})
    if format == "md" and task["artifact"] and task["status"] == "completed":
        return Response(task["artifact"]["markdown"], media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="report-{tid}-v{task["version"]}.md"'})
    raise HTTPException(404, "No current report is available.")

dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
