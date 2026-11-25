import re
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["research", "analyze", "review", "write"]
    objective: str = Field(min_length=1, max_length=2000)
    deps: list[str] = Field(default_factory=list, max_length=12)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[Step] = Field(min_length=3, max_length=12)


def validate_plan(raw):
    plan = Plan.model_validate(raw).model_dump()
    steps = plan["steps"]
    by_id = {s["id"]: s for s in steps}
    if len(by_id) != len(steps):
        raise ValueError("Step IDs must be unique.")
    if len([s for s in steps if s["kind"] == "write"]) != 1:
        raise ValueError("A plan must have exactly one final writing step.")
    for s in steps:
        if len(set(s["deps"])) != len(s["deps"]) or any(d not in by_id for d in s["deps"]):
            raise ValueError("Dependencies must be unique existing step IDs.")
    visiting, done = set(), set()

    def visit(sid):
        if sid in visiting:
            raise ValueError("Workflow connections must not contain a cycle.")
        if sid in done:
            return
        visiting.add(sid)
        for dep in by_id[sid]["deps"]:
            visit(dep)
        visiting.remove(sid)
        done.add(sid)

    for sid in by_id:
        visit(sid)
    writer = next(s for s in steps if s["kind"] == "write")
    ancestors = set()

    def ancestors_of(sid):
        for d in by_id[sid]["deps"]:
            if d not in ancestors:
                ancestors.add(d)
                ancestors_of(d)

    ancestors_of(writer["id"])
    if len(ancestors) != len(steps) - 1:
        raise ValueError("Every step must contribute to the final writing step.")
    if not any(by_id[d]["kind"] == "research" for d in ancestors):
        raise ValueError("The report must depend on a research step.")
    if not any(by_id[d]["kind"] == "review" for d in ancestors):
        raise ValueError("The report must depend on a review step.")
    return plan


def descendants(plan, seeds):
    affected = set(seeds)
    while True:
        expanded = affected | {s["id"] for s in plan["steps"] if set(s["deps"]) & affected}
        if affected == expanded:
            return affected
        affected = expanded


def difference(old, new):
    a, b = [{s["id"]: s for s in p["steps"]} for p in (old, new)]
    added = sorted(b.keys() - a.keys())
    removed = sorted(a.keys() - b.keys())
    updated = sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
    impacted = descendants(old, removed + updated) | descendants(new, added + updated)
    return {"added": added, "removed": removed, "updated": updated, "affected": sorted(impacted)}


def check_citations(text, source_ids):
    cited = set(re.findall(r"\[(S\d+)\]", text))
    if not cited or not cited.issubset(set(source_ids)):
        raise ValueError("Report needs [S#] citations that match current retrieved sources.")
    return sorted(cited)
