# Development record

All entries concern development on 25 November 2026. Operator actions are development checks performed with Codex assistance, not participant observations.

| Decision or change | Reason | Check and result |
|---|---|---|
| Keep the graph and executor on one versioned plan | A diagram must determine what actually executes | Live changes invalidated affected results and reran later steps |
| Separate four role calls and restrict context to upstream outputs and sources | Keep roles inspectable and avoid recursive duplication of tool logs | A real report completed; context inspection confirmed separate role calls |
| Preserve preview/apply across text, form and graph editing | Show consequences before applying an intervention | Browser text and form edits, plus a graph-added analysis node with revised dependencies, changed live execution |
| Retain result history and identify human revisions | Corrections must not silently overwrite evidence | A revised intermediate result reached Writer in version 6; its old AI result remained saved |
| Add one automatic evidence-repair round | Recover from inadequate coverage without repeated confirmation | Live Reviewer detected missing CrewAI evidence; two nodes were added in version 2, executed, and escalated remaining gaps |
| Respect the current step objective during review | The initial review kept treating disclosed unknowns as mandatory measurements after scope was narrowed | Revised review instruction and form objective allowed a bounded, explicitly limited report |
| Change default search from Tavily to DeepSeek | Tavily keyless returned a real HTTP 429 and no extra key was available | Search/Fetch probes succeeded; the same failed task resumed and completed; a normal case also completed |
| Clean serialized webpage state | A real documentation page returned framework data rather than readable prose | Direct retrieval of the same URL and HTML cleanup returned the article; unit check removes navigation and scripts |
| Refit the graph on version changes and give nodes explicit dimensions | Added nodes initially hid earlier steps | Browser check showed all seven nodes after reload/version change |
| Provide a temporary development-root symlink | Vite decoded a percent character in the course directory as a malformed URL | Development server returned the application HTML; source location stayed unchanged |

## Verification

Fourteen automated cases cover graph cycles, dangling dependencies, duplicate IDs, unsupported activities, disconnected steps, fabricated/missing citation IDs, real-executor scheduling through injected services, automatic repair, stale edits, duplicate application, affected reruns, result revisions, failure recovery, restart state, pause/application races, and HTML cleanup/private URL rejection. Test services are explicitly labelled and never selected by the normal application.

Live evidence records a normal research task, correction of a research comparison, and recovery from a genuine search-provider rate limit. The browser checked plan preview, step inspection, workflow changes, final report, download and refresh. Checks do not establish factual completeness or usability benefits. An early fetched page contained script state; its failure and the later cleanup verification are retained in the local development evidence.

## Boundaries

The application runs on loopback without accounts. Do not expose it as a public service. Reports and source records remain local unless exported. Restart recovery resumes at a saved application step boundary, rather than guaranteeing exactly-once execution of an interrupted external call. Citation validation checks identity, not entailment. A larger search budget or broader task scope requires deliberate configuration.

## Assistance examples

1. Codex was asked to implement the confirmed supervision requirements. A single preview/apply path was retained so graph edits and natural-language changes share validation.
2. An initial context design nested complete upstream logs. It was replaced with relevant upstream outputs and source IDs; tool logs remain separately inspectable.
3. Browser testing exposed graph visibility and path-encoding errors. Both were corrected and rechecked instead of recording the first implementation as finished.

The student supplied the scope and interaction decisions. This record describes assisted development checks and makes no claim that the student personally performed each automated or browser operation.
