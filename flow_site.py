import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="Flow General")


@app.cell
def _():
    import html
    import importlib
    import sys
    from uuid import uuid4

    import marimo as mo

    # Same native Marimo notebook in Python server and browser preview.
    browser = sys.platform == "emscripten"
    runtime = None if browser else importlib.import_module("flow_site_runtime")
    return browser, html, mo, runtime, uuid4


@app.cell
def _():
    starter = [
        {"id": "flow-source", "title": "01 · Read the system", "kind": "reading",
         "text": "A predator and its prey form a coupled dynamical system. Prey grow when predators are scarce; predator populations grow when food is abundant. The interaction can produce cycles. A mathematical model is a statement of assumptions, not evidence that a particular ecosystem obeys them.",
         "origin": "built-in reading", "intent": "", "params": {}},
        {"id": "flow-model", "title": "02 · Make the equation executable", "kind": "simulation",
         "text": "Lotka–Volterra predator/prey model: dx/dt = 1.1x − 0.4xy; dy/dt = 0.1xy − 0.9y. Explore how initial populations change the trajectories.",
         "origin": "built-in simulation", "intent": "", "params": {"prey": 10, "pred": 5}},
        {"id": "flow-question", "title": "03 · Challenge the assumptions", "kind": "reading",
         "text": "What changes if resources are finite? How would a carrying capacity alter the prey equation? Which observations would distinguish the two models?",
         "origin": "built-in question", "intent": "", "params": {}},
    ]
    return (starter,)


@app.cell
def _(mo, runtime, starter):
    get_workspace, set_workspace = mo.state(runtime.load(starter) if runtime else starter,
                                           allow_self_loops=True)
    get_focus, set_focus = mo.state("flow-model", allow_self_loops=True)
    get_notice, set_notice = mo.state("")
    get_events, set_events = mo.state([])
    return get_events, get_focus, get_notice, get_workspace, set_events, set_focus, set_notice, set_workspace


@app.cell
def _(get_workspace, runtime, set_events, set_workspace):
    def add_cell(cell):
        if runtime:
            set_workspace(runtime.add(cell))
        else:
            set_workspace(lambda old: old + [cell] if not any(x["id"] == cell["id"] for x in old) else old)

    def patch_cell(cell_id, patch, event):
        if runtime:
            set_workspace(runtime.update(cell_id, patch, event))
        else:
            set_workspace(lambda old: [{**c, **patch} if c["id"] == cell_id else c for c in old])
        set_events(lambda old: (old + [{"cell_id": cell_id, **event}])[-100:])

    return add_cell, patch_cell


@app.cell
def _(mo):
    # Real RK2 integration; browser and server execute the same algorithm.
    def trajectories(prey, pred, steps=400, dt=0.02):
        x, y = float(prey), float(pred)
        xs, ys = [x], [y]
        for _ in range(steps):
            dx, dy = 1.1*x - 0.4*x*y, 0.1*x*y - 0.9*y
            a, b = x + dx*dt/2, y + dy*dt/2
            x = max(0.0, x + (1.1*a - 0.4*a*b)*dt)
            y = max(0.0, y + (0.1*a*b - 0.9*b)*dt)
            xs.append(x)
            ys.append(y)
        return xs, ys

    def chart(prey, pred, compact=False):
        xs, ys = trajectories(prey, pred)
        w, h = 620, (108 if compact else 270)
        top = max(max(xs), max(ys), 1)
        def points(series):
            return " ".join(f"{36+i*(w-52)/(len(series)-1):.2f},{h-22-v*(h-36)/top:.2f}"
                            for i,v in enumerate(series))
        return mo.Html(f'<svg role="img" aria-label="Simulated predator and prey populations over time" viewBox="0 0 {w} {h}" style="width:100%;height:auto">'
                       f'<path d="M36 10 V{h-22} H{w-16}" stroke="#8a929c" fill="none"/>'
                       f'<text x="3" y="16" font-size="10" fill="currentColor">{top:.0f}</text>'
                       f'<text x="9" y="{h-22}" font-size="10" fill="currentColor">0</text>'
                       f'<text x="{w-54}" y="{h-5}" font-size="10" fill="currentColor">t = 8</text>'
                       f'<polyline points="{points(xs)}" stroke="#249e8a" fill="none" stroke-width="2"/>'
                       f'<polyline points="{points(ys)}" stroke="#e38a44" fill="none" stroke-width="2"/></svg>')

    return chart, trajectories


@app.cell
def _(browser, mo):
    _style = mo.Html("""<style>
    .flow-hero{padding:22px 0 16px;border-bottom:1px solid #8884;margin-bottom:12px}
    .flow-label{font:11px ui-monospace,monospace;letter-spacing:.13em;text-transform:uppercase;opacity:.65}
    .flow-title{font-size:32px;font-weight:650;letter-spacing:-.045em;margin:4px 0}
    .flow-cell-title{font-size:16px;font-weight:650;letter-spacing:-.015em}
    .flow-note{font-size:13px;opacity:.75;line-height:1.5}
    </style>""")
    _sidebar = mo.sidebar([
        mo.md("## Flow General"),
        mo.md("**Workspace**  \\nLiving notebook"),
        mo.md("**Runtime**  \\n" + ("Browser · Marimo / WASM" if browser else "Server · Marimo / Python")),
        mo.md("**Attention**  \\nOpen a cell to work; close it to a compact slide."),
        mo.md("**Shadow**  \\nSupervisor not integrated. Legacy worker is separate."),
        mo.md("[Architecture roadmap](https://github.com/Sketch3m/Flow-General/issues/1)"),
    ], width=240)
    _hero = mo.Html('<div class="flow-hero"><div class="flow-label">Computational notebook / 001</div>'
            '<div class="flow-title">Flow General</div><div class="flow-note">Read. Explore. Execute. '
            'A notebook whose cells become working environments.</div></div>')
    mo.vstack([_style, _sidebar, _hero])
    return


@app.cell
def _(get_notice, mo):
    mo.md(get_notice() or "")
    return


@app.cell
def _(chart, get_focus, get_workspace, html, mo, patch_cell, set_focus, set_notice):
    _focus = get_focus()
    _cards = []
    for _cell in get_workspace():
        _id = _cell["id"]
        _is_open = _id == _focus
        _header = mo.hstack([
            mo.Html('<div><div class="flow-label">' + html.escape(_cell["kind"] + " / " + _cell["origin"])
                    + '</div><div class="flow-cell-title">' + html.escape(_cell["title"]) + '</div></div>'),
            mo.ui.button(label="Collapse" if _is_open else "Open cell",
                         on_click=lambda _v, cid=_id, opened=_is_open: set_focus(None if opened else cid)),
        ], justify="space-between", align="center")
        _parts = [_header]
        if _cell["kind"] == "simulation":
            _params = _cell.get("params") or {"prey": 10, "pred": 5}
            _prey, _pred = _params["prey"], _params["pred"]
            _parts.append(chart(_prey, _pred, compact=not _is_open))
            _parts.append(mo.md(f"🟢 Prey · 🟠 Predator · initial {_prey} / {_pred} · simulated, not observed"))
            if _is_open:
                def _change(name, value, cid=_id, params=_params):
                    patch_cell(cid, {"params": {**params, name: int(value)}},
                               {"kind": "parameter_change", "parameter": name, "value": int(value)})
                _parts.append(mo.hstack([
                    mo.ui.slider(1, 30, value=_prey, label="Initial prey",
                                 on_change=lambda v, f=_change: f("prey", v)),
                    mo.ui.slider(1, 30, value=_pred, label="Initial predators",
                                 on_change=lambda v, f=_change: f("pred", v)),
                ], widths="equal"))
                _parts.append(mo.md(_cell["text"]))
        elif _is_open:
            _parts.append(mo.Html('<div style="white-space:pre-wrap;line-height:1.7">' + html.escape(_cell["text"]) + '</div>'))
        else:
            _text = _cell["text"]
            _parts.append(mo.Html('<div class="flow-note">' + html.escape(_text[:230] + ("…" if len(_text)>230 else "")) + '</div>'))
        if _is_open:
            _intent = mo.ui.text_area(value=_cell.get("intent", ""), label="Main intent", rows=2,
                                      full_width=True, placeholder="What do you want to understand or accomplish?")
            _parts.append(_intent)
            _parts.append(mo.ui.button(label="Save intent", on_click=lambda _v, cid=_id, field=_intent:
                (patch_cell(cid, {"intent": field.value}, {"kind": "main_intent", "text": field.value}),
                 set_notice("Intent saved. No model execution was implied."))))
            _parts.append(mo.accordion({"Source and provenance": mo.md(
                "**Origin:** " + _cell["origin"] + "  \\n**Cell ID:** " + _id +
                ("  \\n**Worker verdict:** " + str(_cell["provenance"]) if _cell.get("provenance") else ""))}))
        _cards.append(mo.vstack(_parts, gap=0.45).style({"padding":"16px", "border":"1px solid #8885",
                      "border-radius":"12px", "border-left": "4px solid #249e8a" if _is_open else "1px solid #8885"}))
    mo.vstack(_cards, gap=0.8)
    return


@app.cell
def _(add_cell, mo, set_focus, set_notice, uuid4):
    new_title = mo.ui.text(label="Title", full_width=True)
    new_text = mo.ui.text_area(label="Source / notes", rows=4, full_width=True)
    source_file = mo.ui.file(filetypes=[".md", ".txt"], multiple=False, kind="button", label="Import text or Markdown")
    def add_note(_v):
        _text = new_text.value.strip()
        _title = new_title.value.strip() or "Untitled cell"
        if source_file.value:
            _file = source_file.value[0]
            if len(_file.contents) > 2_000_000:
                set_notice("Source exceeds the 2 MB import limit.")
                return
            try:
                _text = _file.contents.decode("utf-8")
            except UnicodeDecodeError:
                set_notice("Source must be UTF-8.")
                return
            _title = new_title.value.strip() or _file.name
        if not _text:
            set_notice("Enter a note or select a source file.")
            return
        _cid = "flow-" + uuid4().hex
        add_cell({"id":_cid,"title":_title,"kind":"reading","text":_text,
                  "origin":"user source","intent":"","params":{}})
        set_focus(_cid)
        set_notice("Source added to the ordered notebook.")
    add_button = mo.ui.button(label="Add cell", on_click=add_note)
    mo.accordion({"Add to the notebook": mo.vstack([new_title, new_text, source_file, add_button])})
    return


@app.cell
def _(get_events, get_focus, get_workspace, mo, runtime):
    _workspace = get_workspace()
    _focus = get_focus()
    _events = get_events()
    _context = runtime.meaning(_workspace, _focus) if runtime else None
    _context_view = mo.md("The server concept-graph adapter is unavailable in this browser preview.")
    if _context is not None:
        _context_view = mo.vstack([
            mo.md(f"**{len(_context['links'])}** related-cell links · **{len(_context['gaps'])}** unresolved graph gaps"),
            mo.json(_context),
        ])
    _history = runtime.history()[-20:] if runtime else _events[-20:]
    mo.accordion({"Latent context · inspect": _context_view,
                  "Interaction / subprompt events": mo.json(_history)})
    return


@app.cell
def _(get_focus, get_workspace, mo, runtime, set_notice):
    if runtime:
        def _queue(_v):
            result = runtime.queue(get_workspace(), get_focus() or "")
            set_notice(result["reason"])
        queue_button = mo.ui.button(label="Queue graph-gap investigation", on_click=_queue)
        _panel = mo.vstack([mo.md("### Background investigations"), queue_button,
                   mo.md("Existing gap worker only. Start `python worker.py --watch` separately. "
                         "Saving intent or changing a parameter does not start an autonomous agent.")])
    else:
        _panel = mo.md("### Background investigations\nServer workers are unavailable in the WASM preview. The Python app connects to the existing queue.")
    _panel
    return


@app.cell
def _(mo, runtime):
    poll = mo.ui.refresh(options=["5s", "15s", "1m"], default_interval="5s", label="Refresh worker results") if runtime else None
    poll if runtime else mo.md("")
    return (poll,)


@app.cell
def _(add_cell, mo, poll, runtime, set_focus, set_notice):
    if runtime:
        _tick = poll.value
        _jobs = runtime.status()
        _rows = []
        for _j in _jobs:
            _row = [mo.md(f"**{_j['status']}** · `{_j['id']}` · grounded: {_j.get('grounded', 'not checked')}"),
                    mo.md(str(_j.get("error") or _j.get("stopped") or _j.get("ask") or ""))]
            if _j.get("cell"):
                _proposal = runtime.adopt(_j)
                _row.append(mo.ui.button(label="Open proposal in notebook",
                    on_click=lambda _v, p=_proposal: (add_cell(p), set_focus(p["id"]),
                        set_notice("Proposal retained with its original verification status."))))
            _rows.append(mo.vstack(_row))
        _job_panel = mo.vstack(_rows or [mo.md("_No site investigations queued._")])
    else:
        _job_panel = mo.md("")
    _job_panel
    return


@app.cell
def _(mo):
    mo.accordion({"Shadow · clarification queue": mo.md(
        "Not connected yet. No clarification requests are being manufactured. "
        "Issues #6 and #7 define the real supervisory and clarification protocols.")})
    return


if __name__ == "__main__":
    app.run()
