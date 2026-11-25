"""Controlled tests: injected services never use a real provider or user database."""
import asyncio
from copy import deepcopy
import pytest
from app.domain import validate_plan, difference, check_citations
from app.engine import Engine
from app.services import ServiceError
from app.services import html_text, public_url
from app.store import Store

PLAN = {"steps": [
    {"id": "search", "title": "Search", "kind": "research", "objective": "Find official evidence", "deps": []},
    {"id": "analyze", "title": "Analyze", "kind": "analyze", "objective": "Compare findings", "deps": ["search"]},
    {"id": "review", "title": "Review", "kind": "review", "objective": "Check evidence", "deps": ["analyze"]},
    {"id": "write", "title": "Write", "kind": "write", "objective": "Write report", "deps": ["review"]}]}


class TestServices:
    __test__ = False
    def __init__(self, repair=False, fail=False, gate=None):
        self.repair, self.fail, self.gate = repair, fail, gate
        self.review_count = 0
        self.roles = []
        self.contexts = []

    async def model(self, role, instruction, context, structured=True):
        self.roles.append(role)
        self.contexts.append(deepcopy(context))
        if role == "Planner":
            output = deepcopy(PLAN)
            if context.get("edit"):
                output["steps"][-1]["objective"] = context["edit"]
        elif role == "Writer":
            output = "# Controlled test report\nEvidence [S1]."
        elif role == "Reviewer":
            self.review_count += 1
            output = {"sufficient": not(self.repair and self.review_count == 1),
                      "issues": [{"description": "Gap", "source_ids": ["S1"]}], "repair_query": "additional official evidence", "summary": "Controlled evidence-gap test"}
        elif '"query"' in instruction:
            if self.gate:
                await self.gate.wait()
            output = {"query": "official test source"}
        else:
            output = {"summary": "Controlled source [S1]", "analysis": "Controlled comparison [S1]", "limitations": []}
        return {"output": output, "model": "injected-test-double", "usage": {}}

    async def search(self, query):
        if self.fail:
            raise ServiceError("Controlled tool failure")
        return {"results": [{"url": "https://example.org/evidence", "title": "Controlled evidence"}]}

    async def extract(self, urls):
        return {"results": [{"url": urls[0], "raw_content": "Controlled test source text."}]}


async def ready(tmp_path, svc=None):
    engine = Engine(Store(tmp_path / "test.sqlite"), svc or TestServices())
    task = engine.create("Controlled research test goal")
    await engine.plan(task["id"])
    return engine, engine.store.get(task["id"])


async def run(engine, tid):
    task = engine.store.get(tid)
    task["status"] = "running"
    engine.store.save(task, "test_start", {})
    await engine.run(tid)
    return engine.store.get(tid)


@pytest.mark.parametrize("corruption", ["cycle", "dangling", "duplicate", "unconnected", "invalid_tool"])
def test_reject_invalid_graphs(corruption):
    p = deepcopy(PLAN)
    if corruption == "cycle": p["steps"][0]["deps"] = ["write"]
    if corruption == "dangling": p["steps"][1]["deps"] = ["missing"]
    if corruption == "duplicate": p["steps"][1]["id"] = "search"
    if corruption == "unconnected": p["steps"][2]["deps"] = []
    if corruption == "invalid_tool": p["steps"][0]["kind"] = "shell"
    with pytest.raises(ValueError): validate_plan(p)


def test_reject_fabricated_or_missing_citation():
    with pytest.raises(ValueError): check_citations("Claim [S9]", ["S1"])
    with pytest.raises(ValueError): check_citations("Uncited", ["S1"])


def test_html_cleanup_and_private_urls():
    assert html_text('<nav>Menu</nav><main><h1>Evidence</h1><script>secret()</script><p>Useful</p></main>') == 'Evidence\nUseful'
    for url in ['https://127.0.0.1/x','https://10.0.0.1/','http://example.com','https://user:password@example.com/']:
        with pytest.raises(ServiceError): public_url(url)


@pytest.mark.asyncio
async def test_all_roles_and_traceable_report(tmp_path):
    e,t = await ready(tmp_path)
    done = await run(e,t["id"])
    assert done["status"] == "completed", done["error"]
    assert set(e.services.roles) == {"Planner", "Researcher", "Reviewer", "Writer"}
    assert "https://example.org/evidence" in done["artifact"]["markdown"]
    assert done["results"]["write"]["input"]["sources"][0]["id"] == "S1"
    assert (tmp_path / "checkpoints.sqlite").exists()


@pytest.mark.asyncio
async def test_automatic_repair_changes_actual_execution(tmp_path):
    e,t = await ready(tmp_path,TestServices(repair=True))
    done = await run(e,t["id"])
    assert done["status"] == "completed", done["error"]
    assert done["version"] == 2 and done["automatic_repairs"] == 1
    assert done["states"]["repair_search"] == "completed"
    assert done["results"]["write"]["input"]["upstream"]["repair_review"]["output"]["sufficient"]


@pytest.mark.asyncio
async def test_form_preview_apply_stale_idempotent_and_rerun(tmp_path):
    e,t = await ready(tmp_path)
    t = await run(e,t["id"])
    old_report = deepcopy(t["artifact"])
    p = deepcopy(t["plan"]);p["steps"][1]["objective"] = "Focus comparison on portability"
    preview = await e.preview(t["id"],1,plan=p)
    assert e.store.get(t["id"])["version"] == 1
    assert preview["diff"]["affected"] == ["analyze", "review", "write"]
    applied = await e.apply(t["id"],preview["id"])
    assert applied["artifact"] is None and applied["states"]["search"] == "completed"
    assert len(applied["history"]) == 4
    assert (await e.apply(t["id"],preview["id"]))["version"] == 2
    with pytest.raises(ValueError, match="stale"): await e.preview(t["id"],1,plan=p)
    done = await run(e,t["id"])
    assert done["status"] == "completed"
    assert done["searches"] == 1
    assert done["results"]["analyze"]["input"]["step"]["objective"] == "Focus comparison on portability"
    assert done["artifact"]["version"] > old_report["version"]


@pytest.mark.asyncio
async def test_human_revision_reaches_writer_preserves_history(tmp_path):
    e,t = await ready(tmp_path);t = await run(e,t["id"])
    revision = {"step_id": "analyze", "output": {"analysis": "HUMAN CORRECTION: focus on local storage [S1]."}}
    p = await e.preview(t["id"],1,revision=revision)
    await e.apply(t["id"],p["id"])
    done = await run(e,t["id"])
    assert done["status"] == "completed"
    assert done["results"]["write"]["input"]["upstream"]["analyze"]["origin"] == "Human revision"
    assert "HUMAN CORRECTION" in str(done["results"]["write"]["input"])
    assert any(r["origin"] == "AI" and r["step_id"] == "analyze" for r in done["history"])


@pytest.mark.asyncio
async def test_natural_language_and_graph_use_common_application(tmp_path):
    e,t = await ready(tmp_path)
    nl = await e.preview(t["id"],1,instruction="Keep report under 200 words")
    await e.apply(t["id"],nl["id"])
    current=e.store.get(t["id"])
    graph=deepcopy(current["plan"])
    graph["steps"].insert(2,{"id":"extra","title":"Extra analysis","kind":"analyze","objective":"Check portability","deps":["analyze"]})
    graph["steps"][3]["deps"]=["extra"]
    p=await e.preview(t["id"],2,plan=graph)
    await e.apply(t["id"],p["id"])
    done=await run(e,t["id"])
    assert done["states"]["extra"] == "completed"
    assert done["results"]["write"]["input"]["step"]["objective"] == "Keep report under 200 words"


@pytest.mark.asyncio
async def test_failure_can_resume_and_restart_is_honest(tmp_path):
    svc=TestServices(fail=True);e,t=await ready(tmp_path,svc)
    failed=await run(e,t["id"])
    assert failed["status"] == "needs_help" and failed["states"]["search"] == "failed"
    svc.fail=False
    failed["states"]["search"]="pending";e.store.save(failed,"test_retry",{})
    done=await run(e,t["id"])
    assert done["status"] == "completed"
    done["status"]="running";done["states"]["write"]="running";e.store.save(done,"test_interruption",{})
    Store(e.store.path).recover()
    recovered=e.store.get(t["id"])
    assert recovered["status"] == "paused" and recovered["states"]["write"] == "pending"


@pytest.mark.asyncio
async def test_pause_at_boundary_prevents_apply_race(tmp_path):
    gate=asyncio.Event();e,t=await ready(tmp_path,TestServices(gate=gate))
    active=e.store.get(t["id"]);active["status"]="running";e.store.save(active,"test_start",{})
    worker=asyncio.create_task(e.run(t["id"]))
    for _ in range(40):
        if e.store.get(t["id"])["states"]["search"]=="running": break
        await asyncio.sleep(.01)
    p=await e.preview(t["id"],1,redo="search")
    with pytest.raises(ValueError,match="Pause"): await e.apply(t["id"],p["id"])
    current=e.store.get(t["id"]);current["status"]="pause_requested";e.store.save(current,"pause_requested",{})
    gate.set();await worker
    paused=e.store.get(t["id"])
    assert paused["status"]=="paused" and paused["states"]["search"]=="completed"
    await e.apply(t["id"],p["id"])
    assert e.store.get(t["id"])["states"]["search"]=="pending"
