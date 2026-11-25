import asyncio
from copy import deepcopy
import json
import os
import re
import uuid
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from .domain import validate_plan, difference, descendants, check_citations
from .services import Services, ServiceError, ROOT, config
from .store import Store, now

PLAN_PROMPT = '''Return JSON {"steps":[{"id":"search","title":"Find sources","kind":"research","objective":"...","deps":[]}, ...]}.
Use 4 or 5 steps, covering research, analysis, review, and one final write. Kinds: research, analyze, review, write.
Each step must contribute through dependencies to the final write. Research precedes review; review precedes writing.
At most two research steps. IDs use letters, digits, underscore, hyphen. No extra fields. Tailor objectives to the user's goal.'''


class Tick(TypedDict):
    task_id: str
    step_id: str
    version: int
    result: dict


class Engine:
    def __init__(self, store=None, services=None):
        self.store = store or Store()
        self.services = services or Services()
        self.locks = {}
        self.workers = {}

    def lock(self, tid):
        return self.locks.setdefault(tid, asyncio.Lock())

    def spawn(self, tid, fn):
        if tid in self.workers and not self.workers[tid].done():
            raise ValueError("This task is already processing. Wait for the current step boundary.")
        worker = asyncio.create_task(fn(tid))
        self.workers[tid] = worker
        return worker

    def create(self, goal):
        tid = uuid.uuid4().hex[:12]
        task = {"id": tid, "goal": goal, "created": now(), "status": "planning", "version": 0,
                "plan": None, "versions": [], "states": {}, "results": {}, "history": [], "sources": [],
                "proposals": {}, "applied": [], "automatic_repairs": 0, "searches": 0, "pages": 0,
                "error": None, "artifact": None, "execution": "live", "model": config()["model"]}
        self.store.save(task, "created", {"goal": goal})
        return task

    async def plan(self, tid):
        try:
            task = self.store.get(tid)
            response = await self.services.model("Planner", PLAN_PROMPT, {"goal": task["goal"]})
            plan = validate_plan(response["output"])
            async with self.lock(tid):
                task = self.store.get(tid)
                task.update(plan=plan, version=1, status="ready", error=None,
                            states={s["id"]: "pending" for s in plan["steps"]})
                task["versions"].append({"version": 1, "plan": plan, "origin": "Planner", "created": now()})
                task["planning_call"] = response
                self.store.save(task, "plan_ready", {"version": 1, "model": response["model"]})
        except (ServiceError, ValueError) as exc:
            task = self.store.get(tid)
            task.update(status="needs_help", error=str(exc))
            self.store.save(task, "planning_failed", {"error": str(exc)})
        except Exception:
            task = self.store.get(tid)
            task.update(status="needs_help", error="Planning failed unexpectedly. Inspect configuration and retry.")
            self.store.save(task, "planning_failed", {"error": task["error"]})

    def context(self, task, step):
        by_id = {s["id"]: s for s in task["plan"]["steps"]}
        ancestors = set()

        def walk(sid):
            for dep in by_id[sid]["deps"]:
                if dep not in ancestors:
                    ancestors.add(dep)
                    walk(dep)
        walk(step["id"])
        # Keep tool logs in storage; send only relevant outputs to downstream roles.
        results = {k: {field: v[field] for field in ("output", "origin", "source_ids")}
                   for k, v in task["results"].items() if k in ancestors}
        source_ids = {s for v in results.values() for s in v.get("source_ids", [])}
        sources = [s for s in task["sources"] if s["id"] in source_ids]
        return {"goal": task["goal"], "step": step, "upstream": results, "sources": sources}

    async def execute(self, state):
        task = self.store.get(state["task_id"])
        step = next(s for s in task["plan"]["steps"] if s["id"] == state["step_id"])
        ctx = self.context(task, step)
        calls = []

        async def model(role, instruction, context, structured=True):
            record = {"tool": "deepseek", "role": role, "parameters": {"instruction": instruction, "context": context}, "started": now()}
            calls.append(record)
            try:
                response = await self.services.model(role, instruction, context, structured)
                record.update(returned=response, status="completed", finished=now())
                return response["output"]
            except ServiceError as exc:
                record.update(status="failed", error=str(exc), finished=now())
                raise

        async def tool(name, params, fn):
            record = {"tool": name, "parameters": params, "started": now()}
            calls.append(record)
            try:
                response = await fn()
                record.update(status="completed", returned=response, finished=now())
                return response
            except ServiceError as exc:
                record.update(status="failed", error=str(exc), finished=now())
                raise

        result = {"step_id": step["id"], "version": state["version"], "created": now(), "origin": "AI",
                  "calls": calls, "input": ctx, "source_ids": [s["id"] for s in ctx["sources"]], "new_sources": []}
        try:
            if step["kind"] == "research":
                maximum = int(os.getenv("MAX_SEARCHES", "3"))
                max_pages = int(os.getenv("MAX_PAGES", "5"))
                if task["searches"] >= maximum or task["pages"] >= max_pages:
                    raise ServiceError("Task search/page budget reached. Increase MAX_SEARCHES or MAX_PAGES locally and retry, or revise an existing result.")
                query = await model("Researcher", 'Return JSON {"query":"one focused web search query"}.', ctx)
                query = str(query.get("query", "")).strip()[:300]
                if not query:
                    raise ServiceError("Researcher returned an empty query. Revise the objective and retry.")
                async with self.lock(task["id"]):
                    latest = self.store.get(task["id"])
                    latest["searches"] += 1
                    self.store.save(latest, "search_started", {"step": step["id"], "query": query})
                search = await tool(getattr(self.services, "search_tool", "tavily.search"), {"query": query}, lambda: self.services.search(query))
                urls = list(dict.fromkeys(r["url"] for r in search["results"] if r.get("url", "").startswith("https://")))[:min(2, max_pages-task["pages"])]
                if not urls:
                    raise ServiceError("Search did not return an extractable HTTPS source.")
                async with self.lock(task["id"]):
                    latest = self.store.get(task["id"])
                    latest["pages"] += len(urls)
                    self.store.save(latest, "extract_started", {"step": step["id"], "urls": urls})
                extracted = await tool(getattr(self.services, "extract_tool", "tavily.extract"), {"urls": urls}, lambda: self.services.extract(urls))
                next_id = len(task["sources"]) + 1
                for item in extracted["results"]:
                    if item.get("url") not in urls or not item.get("raw_content"):
                        continue
                    title = next((r.get("title", "Source") for r in search["results"] if r["url"] == item["url"]), "Source")
                    result["new_sources"].append({"id": f"S{next_id}", "url": item["url"], "title": title,
                        "text": item["raw_content"][:9000], "retrieved": now(), "step": step["id"]})
                    next_id += 1
                if not result["new_sources"]:
                    raise ServiceError("Extraction returned no usable content for the searched URLs.")
                result["source_ids"] = list(dict.fromkeys(result["source_ids"] + [s["id"] for s in result["new_sources"]]))
                output = await model("Researcher", 'Return JSON {"summary":"evidence summary with [S#] citations","limitations":["..."]}.',
                                     {"goal": task["goal"], "objective": step["objective"], "sources": result["new_sources"]})
            elif step["kind"] == "analyze":
                output = await model("Researcher", 'Return JSON {"analysis":"comparison using [S#] citations","limitations":["..."]}.', ctx)
            elif step["kind"] == "review":
                output = await model("Reviewer", 'Return JSON {"sufficient":true or false,"issues":[{"description":"...","source_ids":["S1"]}],"repair_query":"focused query if evidence missing","summary":"short justification"}. Check evidence support against the current step objective, which may explicitly narrow the original goal. Sufficient means enough evidence for that scoped report; documented unknowns may remain if the objective permits them. Do not require benchmarks unless explicitly requested. Cite only supplied source IDs.', ctx)
                if not isinstance(output.get("sufficient"), bool) or not isinstance(output.get("issues"), list):
                    raise ServiceError("Reviewer returned an invalid assessment.")
                ids = {s["id"] for s in ctx["sources"]}
                if any(not set(issue.get("source_ids", [])).issubset(ids) for issue in output["issues"]):
                    raise ServiceError("Reviewer cited a source that was not retrieved.")
            else:
                if not ctx["sources"]:
                    raise ServiceError("Writing needs current retrieved sources. Reconnect research and review dependencies.")
                text = await model("Writer", "Write the requested research report in Markdown. Cite claims with [S1], [S2], etc. Use only supplied sources. Do not add a references section or URLs; the application attaches the actual source list. Explain evidence limitations. Follow the writing objective and any human revisions in upstream results.", ctx, False)
                cited = check_citations(text, [s["id"] for s in ctx["sources"]])
                if re.search(r"https?://", text):
                    raise ServiceError("Writer added unchecked URLs. Retry to use source IDs only.")
                output = {"report": text + "\n\n## Sources\n" + "\n".join(
                    f"- [{s['id']}] [{s['title']}]({s['url']})" for s in ctx["sources"] if s["id"] in cited)}
            result.update(output=output, status="completed")
        except (ServiceError, ValueError, KeyError, TypeError) as exc:
            result.update(status="failed", error=str(exc) if isinstance(exc, (ServiceError, ValueError)) else "Model output did not match the required schema. Retry or revise the objective.")
        return {"result": result}

    async def run(self, tid):
        try:
            checkpoint_path = self.store.path.parent / "checkpoints.sqlite"
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                graph = StateGraph(Tick).add_node("execute_step", self.execute).add_edge(START, "execute_step").add_edge("execute_step", END).compile(checkpointer=saver)
                for _ in range(24):
                    async with self.lock(tid):
                        task = self.store.get(tid)
                        if task["status"] == "pause_requested":
                            task["status"] = "paused"
                            self.store.save(task, "paused", {"message": "Paused at a saved step boundary."})
                            return
                        if task["status"] != "running":
                            return
                        steps = task["plan"]["steps"]
                        ready = [s for s in steps if task["states"][s["id"]] == "pending" and all(task["states"][d] == "completed" for d in s["deps"])]
                        if not ready:
                            raise ValueError("No executable step is available. Inspect dependencies and results.")
                        step = ready[0]
                        version = task["version"]
                        task["states"][step["id"]] = "running"
                        self.store.save(task, "step_started", {"step": step["id"], "version": version})
                    state = await graph.ainvoke({"task_id": tid, "step_id": step["id"], "version": version},
                        {"configurable": {"thread_id": f"{tid}:{version}:{step['id']}:{uuid.uuid4().hex[:8]}"}})
                    result = state["result"]
                    async with self.lock(tid):
                        task = self.store.get(tid)
                        if task["version"] != version:
                            task["history"].append({**result, "status": "superseded"})
                            self.store.save(task, "late_result_ignored", {"step": step["id"], "version": version})
                            return
                        task["history"].append(deepcopy(result))
                        if result["status"] == "failed":
                            task["states"][step["id"]] = "failed"
                            task.update(status="needs_help", error=result["error"])
                            self.store.save(task, "step_failed", {"step": step["id"], "error": result["error"]})
                            return
                        task["results"][step["id"]] = result
                        task["sources"].extend(result["new_sources"])
                        task["states"][step["id"]] = "completed"
                        self.store.save(task, "step_completed", {"step": step["id"], "version": version})
                        if step["kind"] == "review" and not result["output"]["sufficient"]:
                            if task["automatic_repairs"] < 1:
                                self.auto_repair(task, step, result["output"])
                            else:
                                task.update(status="needs_help", error="Evidence is still insufficient after one automatic repair. Revise the review result or research objective, then resume.")
                                self.store.save(task, "evidence_needed", {"step": step["id"], "assessment": result["output"]})
                                return
                        if step["kind"] == "write":
                            task["artifact"] = {"version": version, "step": step["id"], "created": now(), "markdown": result["output"]["report"]}
                            task.update(status="completed", error=None)
                            self.store.save(task, "completed", {"version": version})
                            return
                raise ValueError("Execution step limit reached. Inspect the workflow before resuming.")
        except Exception as exc:
            task = self.store.get(tid)
            task.update(status="needs_help", error=str(exc) if isinstance(exc, ValueError) else "Execution interrupted unexpectedly. Saved results are retained; retry from the step boundary.")
            for sid, state in task["states"].items():
                if state == "running":
                    task["states"][sid] = "failed"
            self.store.save(task, "execution_error", {"error": task["error"]})

    def auto_repair(self, task, reviewer, assessment):
        old = task["plan"]
        new = deepcopy(old)
        repair_id, check_id = "repair_search", "repair_review"
        ids = {s["id"] for s in old["steps"]}
        while repair_id in ids:
            repair_id += "x"
        while check_id in ids:
            check_id += "x"
        for s in new["steps"]:
            s["deps"] = [check_id if dep == reviewer["id"] else dep for dep in s["deps"]]
        new["steps"].extend([
            {"id": repair_id, "title": "Fill evidence gap", "kind": "research", "objective": str(assessment.get("repair_query") or assessment["summary"]), "deps": [reviewer["id"]]},
            {"id": check_id, "title": "Recheck evidence", "kind": "review", "objective": "Check whether the reported evidence gaps are now resolved.", "deps": [repair_id]}])
        new = validate_plan(new)
        diff = difference(old, new)
        task["automatic_repairs"] += 1
        self.commit_plan(task, new, diff, "automatic", assessment["summary"], assessment["issues"])

    def commit_plan(self, task, plan, diff, origin, reason, evidence=None, revision=None):
        previous = deepcopy(task["results"])
        task["version"] += 1
        task["plan"] = plan
        affected = set(diff["affected"])
        task["results"] = {k: v for k, v in previous.items() if k not in affected}
        task["states"] = {s["id"]: "completed" if s["id"] in task["results"] else "pending" for s in plan["steps"]}
        if revision:
            sid = revision["step_id"]
            old = previous[sid]
            revised = {**deepcopy(old), "version": task["version"], "origin": "Human revision", "created": now(), "output": revision["output"], "calls": []}
            task["results"][sid] = revised
            task["history"].append(deepcopy(revised))
            task["states"][sid] = "completed"
        task["artifact"] = None
        change = {"version": task["version"], "plan": deepcopy(plan), "origin": origin, "reason": reason,
                  "evidence": evidence or [], "diff": diff, "created": now()}
        task["versions"].append(change)
        task["latest_change"] = change
        task["error"] = None
        self.store.save(task, "workflow_changed", change)

    async def preview(self, tid, version, plan=None, instruction=None, redo=None, revision=None):
        task = self.store.get(tid)
        if version != task["version"]:
            raise ValueError("This edit is stale. Refresh the current version and preview again.")
        if not task["plan"]:
            raise ValueError("Generate a plan first.")
        reason = "Human workflow edit"
        if instruction:
            response = await self.services.model("Planner", PLAN_PROMPT + " Revise the supplied plan to follow the edit. Preserve unchanged IDs and objectives. Return the entire plan JSON.",
                 {"goal": task["goal"], "plan": task["plan"], "edit": instruction})
            plan = response["output"]
            reason = instruction
        new = validate_plan(plan or task["plan"])
        diff = difference(task["plan"], new)
        if redo or revision:
            sid = redo or revision["step_id"]
            if sid not in {s["id"] for s in new["steps"]}:
                raise ValueError("Select an existing step to redo or revise.")
            diff["affected"] = sorted(set(diff["affected"]) | descendants(new, [sid]))
            diff["updated"] = sorted(set(diff["updated"]) | {sid})
            reason = f"Human {'revision' if revision else 'redo'} of {sid}"
        if revision:
            sid = revision["step_id"]
            step = next(s for s in new["steps"] if s["id"] == sid)
            if sid not in task["results"]:
                raise ValueError("Only completed results can be revised.")
            if not isinstance(revision["output"], dict) or not revision["output"]:
                raise ValueError("A revised result must be a nonempty JSON object.")
            if step["kind"] == "write":
                raise ValueError("Revise upstream results and rerun writing to keep citations traceable.")
            if step["kind"] == "review" and (not isinstance(revision["output"].get("sufficient"), bool) or not isinstance(revision["output"].get("issues"), list)):
                raise ValueError("Review revisions require sufficient (boolean) and issues (list).")
        if not diff["affected"]:
            raise ValueError("There are no changes to apply.")
        proposal = {"id": uuid.uuid4().hex, "base_version": version, "plan": new, "diff": diff,
                    "reason": reason, "revision": revision, "created": now()}
        async with self.lock(tid):
            latest = self.store.get(tid)
            if latest["version"] != version:
                raise ValueError("Workflow changed during preview. Refresh and preview again.")
            latest["proposals"][proposal["id"]] = proposal
            self.store.save(latest, "change_previewed", {"id": proposal["id"], "diff": diff})
        return proposal

    async def apply(self, tid, proposal_id):
        async with self.lock(tid):
            task = self.store.get(tid)
            if proposal_id in task["applied"]:
                return task
            p = task["proposals"].get(proposal_id)
            if not p:
                raise ValueError("Preview not found. Preview the edit again.")
            if p["base_version"] != task["version"]:
                raise ValueError("Preview is stale. Refresh the current workflow and preview again.")
            if task["status"] in {"running", "pause_requested", "planning"}:
                raise ValueError("Pause and wait for the saved step boundary before applying this change.")
            self.commit_plan(task, p["plan"], p["diff"], "human", p["reason"], revision=p["revision"])
            task["applied"].append(proposal_id)
            task["status"] = "ready" if not task["results"] else "paused"
            self.store.save(task, "change_applied", {"proposal": proposal_id, "version": task["version"]})
            return task
