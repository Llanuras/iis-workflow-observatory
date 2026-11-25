import React, {useState, useEffect, useMemo} from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow, Background, Controls, MiniMap, Handle, Position, type NodeProps, type Node, type Edge} from '@xyflow/react';
import {Orbit, Plus, ArrowLeft, Play, Pause, FileText, Download, Check, Search, ShieldCheck, PenLine, Layers, ChevronRight, X, RefreshCw, GitBranch, ExternalLink} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '@xyflow/react/dist/style.css';
import './style.css';

type Step = {id:string; title:string; kind:string; objective:string; deps:string[]};
type Plan = {steps:Step[]};
type Result = {output:Record<string,unknown>; input:unknown; calls:Record<string,unknown>[]; source_ids:string[]; origin:string};
type Diff = {added:string[];removed:string[];updated:string[];affected:string[]};
type Change = {version:number;origin:string;reason:string;evidence:unknown[];diff:Diff};
type Proposal = {id:string;diff:Diff;reason:string;plan:Plan};
type Task = {id:string;goal:string;status:string;version:number;plan:Plan|null;states:Record<string,string>;results:Record<string,Result>;sources:{id:string;title:string;url:string;text:string}[];error:string|null;artifact:{markdown:string;version:number}|null;latest_change?:Change;versions:Change[];searches:number;pages:number;history:Result[]};
type Event = {id:number;kind:string;created:string;data:Record<string,unknown>};
const role:Record<string,string> = {research:'Researcher',analyze:'Researcher',review:'Reviewer',write:'Writer'};
const icons:Record<string,typeof Search>={research:Search,analyze:Layers,review:ShieldCheck,write:PenLine};
const label=(s:string)=>s.replaceAll('_',' ');
const json=(x:unknown)=>JSON.stringify(x,null,2);
async function api<T>(path:string,body?:unknown):Promise<T>{
  const r=await fetch('/api'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok){let text='Request failed';try {const d=await r.json();text=typeof d.detail==='string'?d.detail:json(d.detail)} catch {text=await r.text()}throw new Error(text)}
  return r.json();
}
function StepNode({data,selected}:NodeProps){
  const s=data.step as Step;const state=data.state as string;const Icon=icons[s.kind]||Layers;
  return <div className={`step-node ${selected?'selected':''} ${data.changed?'changed':''}`}>
    <Handle type="target" position={Position.Left}/>
    <div className="node-role"><Icon size={15}/>{role[s.kind]}<span className="node-id">{s.id}</span></div>
    <strong>{s.title}</strong><div className={`status ${state}`}><i/>{label(state)}</div>
    {data.changed?<div className="change-label">Workflow change</div>:null}
    <Handle type="source" position={Position.Right}/>
  </div>
}
const nodeTypes={step:StepNode};

function App(){
  const [tasks,setTasks]=useState<{id:string;goal:string;status:string;version:number}[]>([]);
  const [task,setTask]=useState<Task|null>(null);const [tid,setTid]=useState<string|null>(new URLSearchParams(location.search).get('task'));
  const [health,setHealth]=useState<{model_ready:boolean;model:string}|null>(null);
  const [goal,setGoal]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [selected,setSelected]=useState<string|null>(null);const [tab,setTab]=useState('step');const [page,setPage]=useState('workflow');
  const [draft,setDraft]=useState<Plan|null>(null);const [editMode,setEditMode]=useState(false);const [instruction,setInstruction]=useState('');
  const [proposal,setProposal]=useState<Proposal|null>(null);const [events,setEvents]=useState<Event[]>([]);const [live,setLive]=useState(true);
  const [revision,setRevision]=useState('');const [position,setPosition]=useState<Record<string,{x:number;y:number}>>({});
  async function refresh(){if(tid){const t=await api<Task>('/tasks/'+tid);setTask(t);return t}}
  useEffect(()=>{api<typeof health>('/health').then(setHealth).catch(e=>setError(e.message));api<typeof tasks>('/tasks').then(setTasks).catch(e=>setError(e.message))},[tid]);
  useEffect(()=>{
    setTask(null);setEvents([]);setProposal(null);setDraft(null);setEditMode(false);setPage('workflow');setSelected(null);setPosition({});
    if(!tid)return;
    refresh().catch(e=>setError(e.message));
    const url=new URL(location.href);url.searchParams.set('task',tid);history.replaceState({},'',url);
    const stream=new EventSource('/api/tasks/'+tid+'/events');
    stream.onopen=()=>setLive(true);stream.onerror=()=>setLive(false);
    stream.onmessage=e=>{const event=JSON.parse(e.data) as Event;setEvents(old=>old.some(x=>x.id===event.id)?old:[...old,event]);refresh().catch(e=>setError(e.message))};
    return ()=>stream.close();
  },[tid]);
  useEffect(()=>{if(task?.plan&&!editMode){setDraft(structuredClone(task.plan));if(!selected||!task.plan.steps.some(s=>s.id===selected))setSelected(task.plan.steps[0]?.id||null)}},[task?.version,task?.plan,editMode]);
  useEffect(()=>{if(task?.results[selected||''])setRevision(json(task.results[selected!].output));else setRevision('')},[selected,task?.version,task?.results]);
  async function act(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  function home(){setTid(null);setTask(null);history.replaceState({},'',location.pathname)}
  async function create(){await act(async()=>{const t=await api<Task>('/tasks',{goal});setTid(t.id);setTask(t)})}
  async function preview(body:Record<string,unknown>){await act(async()=>{const p=await api<Proposal>('/tasks/'+tid+'/preview',{version:task!.version,...body});setProposal(p)})}
  const plan=editMode&&draft?draft:task?.plan;
  const step=plan?.steps.find(s=>s.id===selected);
  const failed=task?.history.filter((r:Result&{step_id?:string})=>r.step_id===selected).at(-1);
  const result=task?.results[selected||'']||(failed?{...failed,output:failed.output||{error:(failed as Result&{error?:string}).error}}:undefined);
  const highlighted=proposal?.diff||task?.latest_change?.diff;
  const {nodes,edges}=useMemo(()=>{
    if(!plan)return {nodes:[] as Node[],edges:[] as Edge[]};
    const depths:Record<string,number>={};
    function depth(s:Step,seen:string[]=[]):number {if(seen.includes(s.id))return 0;if(depths[s.id]!==undefined)return depths[s.id];return depths[s.id]=s.deps.length?1+Math.max(...s.deps.map(d=>{const dep=plan!.steps.find(x=>x.id===d);return dep?depth(dep,[...seen,s.id]):0})):0}
    const rows:Record<number,number>={};
    const ns=plan.steps.map(s=>{const d=depth(s);const row=rows[d]||0;rows[d]=row+1;return {id:s.id,type:'step',width:230,height:120,initialWidth:230,initialHeight:120,selected:s.id===selected,position:position[s.id]||{x:d*285,y:row*170+90},data:{step:s,state:task?.states[s.id]||'pending',changed:highlighted?[...highlighted.added,...highlighted.updated].includes(s.id):false}}});
    return {nodes:ns,edges:plan.steps.flatMap(s=>s.deps.map(d=>({id:d+'>'+s.id,source:d,target:s.id,animated:task?.states[s.id]==='running',style:{stroke:highlighted?.affected.includes(s.id)?'#bf762f':'#b7c8c5',strokeWidth:2}})))}
  },[plan,selected,task?.states,highlighted,position]);
  function updateStep(key:keyof Step,value:string|string[]){if(!draft||!selected)return;setEditMode(true);setDraft({...draft,steps:draft.steps.map(s=>s.id===selected?{...s,[key]:value}:s)})}
  function graphChange(steps:Step[]){setEditMode(true);setDraft({steps})}
  const running=task?.status==='running'||task?.status==='pause_requested';
  const completed=task?Object.values(task.states).filter(s=>s==='completed').length:0;
  return <div className="app">
    <aside className="rail"><button className="brand" onClick={home} aria-label="Task centre"><Orbit size={28}/></button><button className={!tid?'rail-active':''} onClick={home} title="Task centre"><Layers/></button><div className="rail-bottom"><div className="avatar">WO</div></div></aside>
    <div className="shell"><header className="global"><button className="wordmark" onClick={home}>Workflow <b>Observatory</b></button><span className="workspace-label">PERSONAL WORKSPACE</span><span className="model-pill"><i className={health?.model_ready?'online':''}/>{health?.model||'Connecting'}</span></header>
    {error&&<div className="error" role="alert">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></button></div>}
    {!tid?<main className="home"><div className="eyebrow">YOUR WORK, WITH OVERSIGHT</div><h1>A clearer view of<br/>how work gets done.</h1><p className="intro">Turn a research question into a working plan.<br/>Follow the evidence. Shape what happens next.</p>
      <section className="create-card"><div className="section-label"><Plus size={17}/> NEW RESEARCH TASK</div><label htmlFor="goal">What would you like to investigate?</label><textarea id="goal" value={goal} onChange={e=>setGoal(e.target.value)} placeholder="Compare two tools, investigate an approach, or explore a technical question…" rows={4} maxLength={3000}/><div className="create-footer"><span><Search size={15}/> Web research <span className="dot">·</span><FileText size={15}/> Cited report</span><button className="primary" disabled={busy||goal.trim().length<10||!health?.model_ready} onClick={create}>Create plan <ChevronRight size={16}/></button></div>{!health?.model_ready&&<p className="muted">Configure DEEPSEEK_API_KEY in the local .env file, then reload.</p>}</section>
      <div className="recent-heading"><h2>Recent tasks</h2><span>{tasks.length} saved</span></div><div className="task-list">{tasks.length?tasks.map(t=><button key={t.id} onClick={()=>setTid(t.id)}><div className="task-icon"><GitBranch size={20}/></div><div><strong>{t.goal}</strong><span>Workflow v{t.version} · {label(t.status)}</span></div><ChevronRight size={18}/></button>):<p className="muted">Your research tasks and saved workflows will appear here.</p>}</div>
    </main>:!task?<main className="home"><p>Loading saved workflow…</p></main>:<>
      <div className="task-header"><button className="back" onClick={home}><ArrowLeft size={16}/> Tasks</button><div className="task-title"><h1>{task.goal}</h1><div><span className={`status ${task.status}`}><i/>{label(task.status)}</span><span>Workflow v{task.version}</span><span>{completed}/{task.plan?.steps.length||0} steps complete</span></div></div><div className="task-actions">{task.plan&&task.status!=='completed'&&(running?<button disabled={busy||task.status==='pause_requested'} onClick={()=>act(()=>api('/tasks/'+tid+'/pause',{}))}><Pause size={16}/>{task.status==='pause_requested'?'Pausing…':'Pause'}</button>:<button className="primary" disabled={busy} onClick={()=>act(()=>api('/tasks/'+tid+'/start',{}))}><Play size={16}/>{task.status==='ready'?'Start workflow':'Resume / retry'}</button>)}{task.artifact&&<button className="primary" onClick={()=>setPage('result')}><FileText size={16}/> View report</button>}<a className="button" href={'/api/tasks/'+tid+'/download/json'}><Download size={16}/> Run data</a></div></div>
      {task.error&&<div className="attention" role="alert"><ShieldCheck size={18}/><div><strong>Attention needed</strong><p>{task.error}</p></div>{!task.plan&&<button disabled={busy} onClick={()=>act(()=>api('/tasks/'+tid+'/plan',{}))}><RefreshCw size={16}/> Retry planning</button>}</div>}
      <nav className="page-tabs"><button className={page==='workflow'?'active':''} onClick={()=>setPage('workflow')}><GitBranch size={16}/> Workflow</button><button className={page==='result'?'active':''} disabled={!task.artifact} onClick={()=>setPage('result')}><FileText size={16}/> Report</button><span className="connection"><i className={live?'online':''}/>{live?'Live updates':'Reconnecting…'}</span></nav>
      {page==='result'&&task.artifact?<main className="report"><div className="report-toolbar"><span>REPORT · WORKFLOW V{task.artifact.version}</span><a className="button" href={'/api/tasks/'+tid+'/download/md'}><Download size={16}/> Markdown</a><button onClick={()=>window.print()}>Print / PDF</button></div><article><ReactMarkdown remarkPlugins={[remarkGfm]}>{task.artifact.markdown}</ReactMarkdown></article></main>:<div className="workbench"><section className="canvas-column"><div className="canvas-toolbar"><div><span className="section-label">EXECUTION PLAN</span><span className="muted">{editMode?'Editing draft · not applied':'Select a step to inspect its evidence'}</span></div><div className="toolbar-actions">{editMode?<><button onClick={()=>{setEditMode(false);setDraft(task.plan?structuredClone(task.plan):null)}}>Discard draft</button><button className="primary" disabled={busy} onClick={()=>preview({plan:draft})}>Preview changes</button></>:<button disabled={!task.plan} onClick={()=>{setEditMode(true);setDraft(structuredClone(task.plan));setTab('edit')}}><PenLine size={15}/> Edit workflow</button>}{editMode&&<button onClick={()=>{const id='step_'+Date.now().toString(36);graphChange([...(draft?.steps||[]),{id,title:'New research step',kind:'research',objective:'Find additional evidence for the task.',deps:[]}]);setSelected(id);setTab('edit')}}><Plus size={15}/> Add step</button>}</div></div>
      {task.latest_change&&<button className="change-banner" onClick={()=>setTab('changes')}><GitBranch size={16}/><span><b>{task.latest_change.origin==='automatic'?'Workflow adjusted automatically':'Workflow updated'}</b> · v{task.latest_change.version} · {task.latest_change.reason}</span><ChevronRight size={16}/></button>}
      <div className="flow-area">{task.plan?<ReactFlow key={task.version} nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{padding:0.18}} minZoom={0.25} maxZoom={1.5} onNodeClick={(_,n)=>{setSelected(n.id);if(tab==='changes')setTab('step')}} nodesDraggable={editMode} nodesConnectable={editMode} onNodeDragStop={(_,n)=>setPosition(p=>({...p,[n.id]:n.position}))} onConnect={c=>{if(draft&&c.source&&c.target)graphChange(draft.steps.map(s=>s.id===c.target?{...s,deps:[...s.deps,c.source!]}:s))}} onEdgesDelete={es=>{if(draft&&editMode)graphChange(draft.steps.map(s=>({...s,deps:s.deps.filter(d=>!es.some(e=>e.source===d&&e.target===s.id))})))}} onNodesDelete={ns=>{if(draft&&editMode){graphChange(draft.steps.filter(s=>!ns.some(n=>n.id===s.id)).map(s=>({...s,deps:s.deps.filter(d=>!ns.some(n=>n.id===d))})))}}} deleteKeyCode={editMode?['Backspace','Delete']:null}><Background color="#d6dedb" gap={22}/><Controls showInteractive={false}/><MiniMap pannable zoomable/></ReactFlow>:<div className="planning"><Orbit size={32}/><h2>{task.status==='planning'?'Building your research plan':'Plan unavailable'}</h2><p>The Planner defines steps, roles, and dependencies before execution.</p></div>}</div>
      <div className="legend"><span><i className="legend-dot done"/> Completed</span><span><i className="legend-dot current"/> Running</span><span><i className="legend-dot changed"/> Changed step</span><span className="budget">Searches {task.searches} · Pages {task.pages}</span></div>
      <form className="instruction" onSubmit={e=>{e.preventDefault();preview({instruction})}}><PenLine size={17}/><label className="sr-only" htmlFor="instruction">Describe a workflow change</label><input id="instruction" value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder="Describe a change, e.g. focus the report on local deployment…"/><button className="primary" disabled={busy||!task.plan||!instruction.trim()}>Preview edit <ChevronRight size={16}/></button></form>
      <details className="timeline"><summary>Activity log <span>{events.length} events</span></summary>{events.slice().reverse().map(e=><div key={e.id}><time>{new Date(e.created).toLocaleTimeString()}</time><b>{label(e.kind)}</b><span>{String(e.data.step||e.data.message||'')}</span></div>)}</details></section>
      <aside className="detail-panel"><div className="detail-tabs"><button className={tab==='step'?'active':''} onClick={()=>setTab('step')}>Step details</button><button className={tab==='edit'?'active':''} onClick={()=>setTab('edit')}>Edit step</button><button className={tab==='changes'?'active':''} onClick={()=>setTab('changes')}>Changes</button></div>
      {tab==='changes'?<div className="detail-body"><div className="eyebrow">VERSION HISTORY</div>{task.versions.slice().reverse().map((v,i)=><section className="version-card" key={v.version}><strong>v{v.version} · {v.origin}</strong><p>{v.reason||'Initial research plan'}</p>{v.diff&&<><DiffList diff={v.diff}/><h4>Evidence</h4><pre>{json(v.evidence)}</pre></>}{i===0&&<span className="tag">Current version</span>}</section>)}</div>:step?<div className="detail-body"><div className="detail-heading"><span className="eyebrow">{role[step.kind]} · {step.id}</span><h2>{step.title}</h2><span className={`status ${task.states[step.id]||'pending'}`}><i/>{label(task.states[step.id]||'pending')}</span></div>
        {tab==='edit'?<div className="step-form"><label>Step title<input value={step.title} onChange={e=>updateStep('title',e.target.value)}/></label><label>Role / activity<select value={step.kind} onChange={e=>updateStep('kind',e.target.value)}>{Object.keys(role).map(k=><option key={k} value={k}>{label(k)} · {role[k]}</option>)}</select></label><label>Objective<textarea rows={5} value={step.objective} onChange={e=>updateStep('objective',e.target.value)}/></label><label>Dependencies (comma separated)<input value={step.deps.join(', ')} onChange={e=>updateStep('deps',e.target.value.split(',').map(s=>s.trim()).filter(Boolean))}/></label><div className="button-row"><button className="primary" disabled={busy} onClick={()=>preview({plan:draft})}>Preview changes</button><button className="danger" onClick={()=>{if(draft){graphChange(draft.steps.filter(s=>s.id!==step.id).map(s=>({...s,deps:s.deps.filter(d=>d!==step.id)})));setSelected(null)}}}>Delete step</button></div><p className="muted">Edits are drafts until you preview and apply. Pause a running task before applying.</p></div>:<><h3>Objective</h3><p>{step.objective}</p><h3>Inputs</h3><p className="muted">{step.deps.length?step.deps.join(' → '):'Task goal and research requirements'}</p>{result&&<details><summary>Inspect input context</summary><pre>{json(result.input)}</pre></details>}<h3>Output</h3>{result?<><span className="tag">{result.origin}</span><pre className="output">{json(result.output)}</pre></>:<p className="muted">Output will appear after this step completes.</p>}<h3>Tool calls</h3>{result?.calls.length?result.calls.map((c,i)=><details key={i} className="tool-call"><summary>{String(c.tool)} <span>{String(c.status)}</span></summary><pre>{json(c)}</pre></details>):<p className="muted">No recorded calls for this result.</p>}
        {task.history.filter((r:Result&{step_id?:string})=>r.step_id===step.id).length>0&&<details><summary>Result history</summary><pre>{json(task.history.filter((r:Result&{step_id?:string})=>r.step_id===step.id))}</pre></details>}
        {result&&task.results[step.id]&&<section className="result-edit"><h3>Correct this result</h3><button disabled={busy} onClick={()=>preview({redo:step.id})}><RefreshCw size={15}/> Preview redo & downstream rerun</button>{step.kind!=='write'&&<><label htmlFor="revision">Revised output (JSON)</label><textarea id="revision" rows={5} value={revision} onChange={e=>setRevision(e.target.value)}/><button disabled={busy} onClick={()=>act(async()=>{const output=JSON.parse(revision);const p=await api<Proposal>('/tasks/'+tid+'/preview',{version:task.version,revision:{step_id:step.id,output}});setProposal(p)})}>Preview result revision</button></>}</section>}
        <h3>Sources</h3>{task.sources.filter(s=>result?.source_ids.includes(s.id)).map(s=><a className="source" key={s.id} href={s.url} target="_blank" rel="noreferrer"><span>{s.id}</span>{s.title}<ExternalLink size={13}/></a>)}</>}
      </div>:<div className="detail-body"><Layers size={28}/><h2>Inspect the workflow</h2><p>Select a step to see its objective, inputs, output, and tool evidence.</p></div>}</aside></div>}
    </>}
    <footer>Workflow Observatory <span>Plan visibly. Execute with evidence. Stay in control.</span></footer></div>
    {proposal&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="preview-title"><div className="modal-heading"><GitBranch/><h2 id="preview-title">Review workflow changes</h2><button autoFocus onClick={()=>setProposal(null)} aria-label="Close preview"><X size={18}/></button></div><p>{proposal.reason}</p><DiffList diff={proposal.diff}/><p className="muted">Applying creates a new version. Previous results remain in history. Affected results will be invalidated and rerun when you resume.</p>{running&&<div className="attention">Pause the workflow and wait for the current step to finish before applying.</div>}<div className="modal-actions"><button onClick={()=>setProposal(null)}>Discard preview</button><button className="primary" disabled={busy||running} onClick={()=>act(async()=>{await api('/tasks/'+tid+'/apply',{proposal_id:proposal.id});setProposal(null);setEditMode(false);setTab('changes')})}><Check size={16}/> Apply changes</button></div></section></div>}
  </div>
}
function DiffList({diff}:{diff:Diff}){return <div className="diff-list">{(['added','removed','updated','affected'] as const).map(k=><div key={k}><span>{k==='affected'?'Rerun scope':label(k)}</span><strong>{diff[k].length?diff[k].join(', '):'None'}</strong></div>)}</div>}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
