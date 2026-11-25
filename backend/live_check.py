"""Explicit live acceptance runner; uses real provider configuration and local API."""
import asyncio
import json
import sys
from pathlib import Path
import httpx


async def main():
    output = Path(sys.argv[1])
    goal = "Explain how LangGraph interrupts pause and resume a workflow, including checkpoint and thread ID requirements. Use official documentation. Write a short report of at most 300 words. Describe remaining unknowns; no benchmark or performance claims are required."
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30) as client:
        response=await client.post('/api/tasks',json={"goal":goal});response.raise_for_status();tid=response.json()['id']
        print("Live task:",tid,flush=True)
        started=False;last=None
        for _ in range(180):
            task=(await client.get('/api/tasks/'+tid)).json()
            output.write_text(json.dumps(task,indent=2,ensure_ascii=False))
            state=(task['status'],task['version'],sum(v=='completed' for v in task['states'].values()))
            if state != last: print(state,flush=True);last=state
            if task['status']=='ready' and not started:
                response=await client.post('/api/tasks/'+tid+'/start');response.raise_for_status();started=True
            if task['status'] in {'completed','needs_help'}:
                export=await client.get('/api/tasks/'+tid+'/download/json');export.raise_for_status()
                output.with_name(output.stem+'_含事件.json').write_text(json.dumps(export.json(),indent=2,ensure_ascii=False))
                print('Final:',task['status'],task.get('error'),flush=True);return
            await asyncio.sleep(3)
        print('Acceptance timeout; saved current state, no completion claimed.',flush=True)

asyncio.run(main())
