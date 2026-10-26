import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="nodus · sheet")


@app.cell
def _():
    from pathlib import Path

    import marimo as mo

    import cells
    import delta
    import harness
    import issues
    import localmodels
    import nodus
    import plan

    return Path, cells, delta, harness, issues, localmodels, mo, nodus, plan


@app.cell
def _(Path, cells):
    def seed_sheet() -> list[dict]:
        """The example from the message: prose, an image, a dynamics sentence."""
        base = [
            cells.Cell(
                id="c1",
                text="A duck crosses the street at dusk, and the cars wait. Nobody has decided who has the right of way.",
                role="note",
            ),
            cells.Cell(
                id="c2",
                text="![cat crossing the road](assets/cat.svg)",
                role="note",
            ),
            cells.Cell(
                id="c3",
                text="Predator and prey populations oscillate, and the fox follows the rabbit by about a quarter cycle.",
                role="note",
            ),
            cells.Cell(
                id="c4",
                text="Which of these is a game-theoretic situation rather than a predator-prey one?",
                role="note",
            ),
            cells.Cell(
                id="c5",
                text="None of these systems convinces me that a new claim is true; I want to see what each one treats as evidence.",
                role="seed",
            ),
        ]
        return [c.to_dict() for c in cells.assign(base)]

    def paper_cells() -> list[dict]:
        out = []
        for i, p in enumerate(sorted(Path("papers").glob("*.md"))):
            out.append(
                cells.Cell(
                    id=f"p{i + 1}",
                    text=p.read_text(encoding="utf-8"),
                    origin="paper",
                    role="paper",
                    meta={"file": p.name},
                ).to_dict()
            )
        return out

    return paper_cells, seed_sheet


@app.cell
def _(mo, seed_sheet):
    get_cells, set_cells = mo.state(seed_sheet())
    get_log, set_log = mo.state([])
    return get_cells, get_log, set_cells, set_log


@app.cell
def _(cells, delta, get_cells, mo, paper_cells, set_cells, set_log):
    def _reset():
        return [
            c.to_dict()
            for c in cells.assign(
                [
                    cells.Cell(id="c1", text="A duck crosses the street at dusk, and the cars wait."),
                    cells.Cell(id="c2", text="![cat crossing the road](assets/cat.svg)"),
                    cells.Cell(
                        id="c3",
                        text="Predator and prey populations oscillate, and the fox follows the rabbit by about a quarter cycle.",
                    ),
                    cells.Cell(id="c4", text="Which of these is a game-theoretic situation rather than a predator-prey one?"),
                    cells.Cell(
                        id="c5",
                        text="None of these systems convinces me that a new claim is true; I want to see what each one treats as evidence.",
                        role="seed",
                    ),
                ]
            )
        ]

    def _load(_v=None):
        merged = [c for c in get_cells() if c["id"] not in {f"p{i}" for i in range(1, 6)}] + paper_cells()
        delta.append("sheet_state", {"cells": merged}, actor="human")
        set_cells(merged)
        set_log(["loaded 5 arXiv abstracts into the sheet"])

    def _clear(_v=None):
        fresh = _reset()
        delta.append("sheet_state", {"cells": fresh}, actor="human")
        set_cells(fresh)
        set_log(["reset"])

    load = mo.ui.button(label="load 5 papers", on_click=_load)
    clear = mo.ui.button(label="reset sheet", on_click=_clear)
    mo.hstack([load, clear], align="center")
    return load,


@app.cell
def _(cells, delta, get_cells, localmodels, mo, set_cells, set_log):
    def _round():
        cs = [cells.Cell.from_dict(d) for d in get_cells()]
        cells.assign(cs)
        # control events (needle's route, nodus's verdict) land in the log too;
        # the reader sees only the round's text output, never these
        res = cells.step(cs, sink=lambda k, p, a: delta.append(k, p, actor=a))
        if "cell" in res:
            cs.append(res["cell"])
            set_cells([x.to_dict() for x in cs])
            delta.append("cell_add", res["cell"].to_dict(), actor="qwen")
        log = list(res.get("log", []))
        if res.get("stopped"):
            log.append(f"stopped: {res['stopped']}")
        set_log(log)

    available = localmodels.available()
    _state = "qwen up" if available["qwen"] else "qwen down"
    run = mo.ui.button(label="run one round", on_click=lambda _v: _round())
    mo.hstack([run, mo.md(f"needle {'ready' if available['needle'] else 'missing'} · {_state}")], align="center")
    return run,


@app.cell
def _(cells, delta, get_cells, get_log, mo, plan, set_cells, set_log):
    def _swarm():
        cs = [cells.Cell.from_dict(d) for d in get_cells()]
        cells.assign(cs)
        # gaps -> subagents x generations -> needle approves -> bounded lanes;
        # control events (incl. the approval) go to the log panel below
        res = plan.run(cs, sink=lambda k, p, a: delta.append(k, p, actor=a))
        set_cells([x.to_dict() for x in cs])
        set_log(res["log"])

    swarm = mo.ui.button(label="plan a run (needle approves the budget)", on_click=lambda _v: _swarm())
    mo.md("*the open gaps decide how many subagents and generations run; the plan stops on success, on patience, or at the hard cap of 9 batches.*")
    mo.vstack([swarm])
    return (swarm,)


@app.cell
def _(harness, get_log, mo, set_log):
    def _edit():
        out = harness.edit_once()
        set_log(out["log"])

    propose_btn = mo.ui.button(
        label="qwen edits the harness · nodus gates it",
        on_click=lambda _v: _edit(),
    )
    mo.md(
        "*one closed field at a time: qwen proposes from the probe's failure record, "
        "the edit runs the loop on the papers, and nodus keeps it only if gaps close. "
        "every attempt — kept or rejected — lands in `solve/harness_trace.json`.*"
    )
    mo.vstack([propose_btn])
    return (propose_btn,)


@app.cell
def _(mo):
    draft = mo.ui.text_area(
        label="new cell",
        placeholder="type prose, a question, a path to an image, or a predator/prey sentence",
        rows=3,
        full_width=True,
    )
    return (draft,)


@app.cell
def _(cells, delta, get_cells, mo, set_cells, set_log):
    # Edit one existing cell by id. Applied on button press, never on keystroke,
    # so a half-typed sentence cannot re-route the chain.
    edit_id = mo.ui.dropdown(options=[c["id"] for c in get_cells()], value=get_cells()[0]["id"], label="cell")
    edit_text = mo.ui.text_area(label="new text", rows=2, full_width=True)

    def _apply():
        if not edit_text.value.strip():
            return
        cs = [cells.Cell.from_dict(d) for d in get_cells()]
        cells.edit(cs, edit_id.value, edit_text.value.strip())
        set_cells([x.to_dict() for x in cs])
        new_view = next(x.view for x in cs if x.id == edit_id.value)
        # the log keeps the text that was overwritten (fold puts it in `previous`)
        delta.append("cell_edit", {"id": edit_id.value, "text": edit_text.value.strip(), "view": new_view}, actor="human")
        set_log([f"edited {edit_id.value}: view = {new_view}"])

    apply_edit = mo.ui.button(label="apply edit", on_click=lambda _v: _apply())
    mo.vstack([mo.hstack([edit_id, apply_edit], align="center"), edit_text])
    return apply_edit, edit_id, edit_text


@app.cell
def _(cells, delta, draft, get_cells, mo, set_cells, set_log):
    def _add():
        text = draft.value.strip()
        if not text:
            return
        cs = [cells.Cell.from_dict(d) for d in get_cells()]
        c = cells.Cell(id=f"c{len(cs) + 1}", text=text, origin="human", role="note")
        cells.assign([c])
        cs.append(c)
        set_cells([x.to_dict() for x in cs])
        delta.append("cell_add", {"id": c.id, "text": c.text, "view": c.view, "role": c.role}, actor="human")
        set_log([f"added {c.id}: view = {c.view} ({c.why})"])

    add = mo.ui.button(label="add cell", on_click=lambda _v: _add())
    mo.hstack([add], align="center")
    return (add,)


@app.cell
def _(get_cells, mo):
    latent = mo.ui.switch(label="show latent context (nodus only)", value=False)
    qview = mo.ui.switch(label="let qwen choose the view (1/5 correct on the seed cells)", value=False)
    mo.hstack([latent, qview], align="center")
    return latent, qview


@app.cell
def _(Path, cells, get_cells, get_log, latent, mo, qview):
    @mo.cache
    def _qview(text):
        return cells.choose_view(text)

    def _cell_view(c, choice=None):
        kind = choice["view"] if choice else c.view
        _alt = f" · qwen: {choice['view']}" if choice and choice["view"] != c.view else ""
        head = mo.md(
            f"<div style='display:flex;justify-content:space-between;font-size:12px;opacity:.6'>"
            f"<span><b>{c.id}</b> · {c.origin} · {c.role}</span>"
            f"<span>{c.view} — {c.why}{_alt}</span></div>"
        )
        if kind == "image":
            src = c.meta.get("src", "") if kind == c.view else ""
            body = (
                mo.image(src)
                if src and Path(src).exists()
                else mo.md(f"*image cell* — `{src or 'no path'}` not found; drop the file there and it renders.")
            )
        elif kind == "plot":
            body = mo.Html(cells.plot_svg(c.text))
        elif kind == "paper":
            title = c.text.splitlines()[0].lstrip("# ") if c.text else c.id
            body = mo.accordion({title: mo.md(c.text)})
        elif kind in ("question", "claim"):
            note = "question cell" if kind == "question" else "claim cell — checked for a relation, not for truth"
            body = mo.md(f"> {c.text}\n\n*{note}*")
        else:
            body = mo.md(c.text)
        return mo.vstack([head, body])

    _cs = [cells.Cell.from_dict(d) for d in get_cells()]
    cells.assign(_cs)
    _parts = [mo.md("# the sheet"), mo.md(f"{len(_cs)} cells · the view of each cell is inferred from what it says")]
    for c in _cs:
        _parts.append(_cell_view(c, _qview(c.text) if qview.value else None))
    if latent.value:
        _read = cells.read(_cs)
        _lines = ["### latent context", f"{_read['summary']}", ""]
        for l in _read["links"][:6]:
            _lines.append(f"- **{l['a']} ↔ {l['b']}** · {l['n']} shared concepts: {', '.join(l['shared'])}")
        for g in _read["gaps"][:4]:
            _lines.append(f"- gap **{g['id']}** · score {g['score']:.2f} · {g['question'][:110]}")
        _parts.append(mo.accordion({"the graph's reading, not shown in the cells": mo.md("\n".join(_lines))}))
    _log = get_log()
    if _log:
        _parts.append(mo.md("### last round\n" + "\n".join(f"- `{line}`" for line in _log)))
    mo.vstack(_parts)
    return


@app.cell
def _(cells, get_cells, issues, mo):
    @mo.cache
    def _issues_for(text):
        return issues.from_text(text)

    _cs = [cells.Cell.from_dict(d) for d in get_cells()]
    _items = _issues_for(cells.sheet_text(_cs))[:3]
    _lines = ["### issues at the bottom", "*the same board as `board.py`, computed from the sheet*"]
    for i in _items:
        _lines.append(
            f"- **{i.title}** · score {i.score:.2f} · [{i.queries[0]}]({issues.search(i.queries[0])})"
        )
    if not _items:
        _lines.append("- no unbridged gaps in the sheet right now")
    mo.md("\n\n".join(_lines))
    return


@app.cell
def _(delta, get_log, mo):
    # reads the log fresh after any button that updates the round log (get_log
    # is the reactivity hook); read-only - the panel never writes
    _ = get_log()
    _evs = delta.events()
    _ok1, _, _m1 = delta.verify()
    _ok2, _, _m2 = delta.verify_checkpoints()
    _tips = delta.tips()
    _cks = delta.events(kind="checkpoint")
    _lines = [
        "### the log — `solve/delta.jsonl`",
        f"*{len(_evs)} events · {len(_tips)} open tips · lineage: **{'intact' if _ok1 else _m1}** "
        f"· checkpoints: **{'match' if _ok2 else _m2}**",
    ]
    if _cks:
        _last = _cks[-1]["payload"]
        _lines.append(
            f"last checkpoint covers {_last['lines']} lines · receipt `log_sha {_last['log_sha'][:16]}` "
            "(exportable — an external copy makes the notary independent)"
        )
    _lines.append("")
    for _e in _evs[-6:]:
        _par = _e.get("parents") or ([_e["prev"]] if _e.get("prev") else [])
        _tail = f"· base {_par[0][:8]}" if _par else "· root"
        _lines.append(f"- `{_e['seq']}` **{_e['kind']}** · {_e['actor']} {_tail}")
    mo.md("\n".join(_lines))
    return


if __name__ == "__main__":
    app.run()
