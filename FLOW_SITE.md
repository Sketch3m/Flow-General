# Flow General — native Marimo site

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
