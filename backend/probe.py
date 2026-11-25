"""Run from the project root: .venv/bin/python backend/probe.py."""
import asyncio
import json
from app.services import Services, ServiceError, config


async def main():
    svc = Services()
    result = {"config": config(), "mode": "live", "checks": {}}
    for name, call in [
        ("model", lambda: svc.model("Planner", 'Return JSON {"connected": true}.', {"test": "connectivity"})),
        ("search", lambda: svc.search("LangGraph official documentation human oversight")),
        ("extract", lambda: svc.extract(["https://docs.langchain.com/oss/python/langgraph/overview"]))
    ]:
        try:
            data = await call()
            result["checks"][name] = {"ok": True, "result": data}
        except ServiceError as exc:
            result["checks"][name] = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))

asyncio.run(main())
