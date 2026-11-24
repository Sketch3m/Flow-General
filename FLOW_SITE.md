# Flow General — native Marimo site

## Approved UI implementation — Fulfillment × Shadow (2026-11-23)

This version preserves the **SolveIt/nbdev ordered notebook** and adds the
approved interaction split, based on the light Flow-General screenshots:

- **Fulfillment lives inside the focused notebook cell.** Click **Open
  Fulfillment conversation**, then create one or more **nested subchats**.
  Open a child, write another brief/reply, complete it with an explicitly
  **manual** report, and insert that report as a provenance-tagged,
  **unverified** editable notebook cell. Subchats are real navigable
  conversation records, not separate Scout/Critic/Experiment roles.
- **Shadow stays in the right-hand panel.** Scout, Critic, and Experiment are
  **ambient role placeholders**, visibly marked **Not connected** until the
  relevant adapter runs. The existing server graph-gap queue appears in the
  same panel with its real status and review/adoption affordance. Do not call
  it full autonomous Shadow.
- **Server mode:** `flow_fulfillment.py` persists cell root, parent/child
  relationships, message provenance, status and audit events transactionally
  to `FLOW_SITE_DB` (default `solve/flow-site.sqlite3`). A cell has one
  idempotent root. Manual child report-back is atomic; cancelling cascades
  through descendants. No provider calls or fake model completions.
- **Browser/WASM demo:** `docs/index.html` is regenerated from
  `flow_site.py`. It exposes the same nested chat controls with transient
  in-memory state. Every browser-only action is explicitly a **demo**;
  nothing survives reload, and no LLM/agent is called.
- **PandaCode** remains the preferred future native executor. **OpenMausBot**
  supplies thread/delegation semantics, not a second Electron shell. The
  PandaCode execution bridge, real model replies, resumable remote runs,
  automatic Shadow triggers and full v6 browser-worker integration **are not
  present or validated in this slice**.

### Check this implementation

```sh
python -m unittest discover -p 'test_*.py'
python -m marimo check flow_site.py
python -m marimo export html-wasm flow_site.py --mode run --single-file -o flow-preview.html
python -m marimo export html flow_site.py -o flow-server-snapshot.html
```

Focused tests cover cell isolation, nesting limits, messaging, manual
report-back, cancellation and audit events. The exported preview uses Marimo
in WASM, so it requires an internet connection for its external assets.

The app is `flow_site.py`, an actual Marimo notebook, not a custom JavaScript frontend.
It preserves a single ordered notebook with focusable cells, compact slide previews,
an executable predator–prey cell, persistent main intents, and parameter/subprompt
events. Server mode uses the existing concept-graph and gap-worker adapters. This
is a first working vertical slice, not completion of issues #2–#10.

## Private Python server

From the repository root:

```sh
python -m pip install -r requirements.txt
marimo run flow_site.py --host 127.0.0.1 --port 7860
```

Open the URL/token printed by Marimo. Use `marimo edit flow_site.py` for authoring.
In a second terminal, only if you want the legacy gap worker:

```sh
python worker.py --watch
```

This adapter uses the old global queue and model settings, so use a private
single-user workspace. It refuses to replace another notebook's existing
legacy sheet or enqueue while a task is active. The queue still has the known
snapshot/recovery limitations in #3. Worker proposals are not verified facts.
The server notebook's user cells and interaction events use
`solve/flow-site.sqlite3`; keep that file to retain them across restarts.

## Browser preview (still Marimo)

```sh
marimo export html-wasm flow_site.py --mode run --single-file -o flow-preview.html
```

This exports native Marimo/Pyodide reactivity: the simulation, focus/slide
transition, text import and intent/parameter events run in the browser.
It does not run the Python server, persist a shared workspace, execute external
workers, or integrate Shadow. Preview data is in memory. It is safe to publish
as a read-only-code demonstration, not as a shared production backend.

## Container

```sh
docker build -f Dockerfile.flow -t flow-general .
docker run --rm -p 127.0.0.1:7860:7860 -v flow-state:/app/solve flow-general
```

The server keeps Marimo's token authentication enabled. Do not expose the
private shared notebook to the public without authentication, tenant isolation,
and the durable scheduler in #3. Use a private Codespace or VM for the server.

## Validation

```sh
python -m unittest test_flow_site_runtime
marimo check flow_site.py
marimo export html-wasm flow_site.py --mode run --single-file -o flow-preview.html
```

Shadow recovery (#6), indirect clarification (#7), generalized representations
(#8), actual Calyx integration (#4), spoiler-aware close reading, and autonomous
prefetch are still backend roadmap items. The page explicitly labels unavailable
capabilities rather than simulating success.
