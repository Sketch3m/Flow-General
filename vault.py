import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="nodus · vault")


@app.cell
def _():
    import html
    import re
    from pathlib import Path

    import marimo as mo

    import cells
    import delta
    import jobs
    import nodus
    import prune
    import worker

    return Path, cells, delta, html, jobs, mo, nodus, prune, re, worker


@app.cell
def _(html, re):
    # What a reader needs at a glance: which cell they are in (the header), and
    # what the graph did to the model's text (the compressed block). Everything
    # else is folded, because the point is that the long text stays recoverable
    # rather than in the way.
    CSS = """
    .nb{--ink:#1d1b18;--mute:#6f6a5f;--line:#e3dfd5;--rule:#eeebe3;--warm:#f7f0e2;
        --acc:#a8442a;--cool:#2b6478;max-width:1180px;margin:0 auto;padding:0 20px 80px;
        font-family:ui-serif,Georgia,'Iowan Old Style',serif;color:var(--ink)}
    .hdr{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;padding:10px 0 2px;
        font:11px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:#a09889}
    .hdr b{font:600 13px ui-monospace,monospace;letter-spacing:.14em;color:var(--ink)}
    .cellhdr{display:flex;justify-content:space-between;gap:10px;align-items:baseline;
        border-top:1px solid var(--line);padding:8px 0 2px;
        font:9.5px ui-monospace,monospace;letter-spacing:.07em;text-transform:uppercase;color:#a09889}
    .cellhdr b{color:var(--acc);font-weight:600}
    .doc{min-width:0;max-width:72ch;font-size:16px;line-height:1.62}
    .doc p{margin:0 0 .6em}
    .doc h2{font-size:17px;margin:.7em 0 .35em}
    .out{max-width:78ch;border-left:3px solid var(--acc);background:var(--warm);
        padding:8px 12px;margin:4px 0 2px;font-size:15.5px;line-height:1.55}
    .out .s{display:block;margin:0 0 .35em}
    .out .s:last-child{margin-bottom:0}
    .meta{font:10.5px/1.5 ui-monospace,monospace;color:#8d8778;margin-top:3px}
    .chip{font:9.5px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;
        padding:0 4px;margin-left:4px;color:var(--cool);background:#eaf2f6}
    .chip.bad{color:#a8442a;background:#fbeee9;border-color:#eccfc5}
    .strip{border-top:1px solid var(--line);padding-top:10px;margin-top:18px}
    .strip table{border-collapse:collapse;font:11px ui-monospace,monospace;width:100%}
    .strip th{text-align:left;font-weight:400;color:#a09889;letter-spacing:.07em;
        text-transform:uppercase;font-size:9px;padding:0 8px 3px 0}
    .strip td{padding:2px 8px 2px 0;border-top:1px dotted var(--line);color:#4a4438}
    .st-open{color:#8d8778}.st-running{color:#2b6478}.st-done{color:#5b7a52}.st-failed{color:#a8442a}
    .hint{font:10.5px/1.5 ui-monospace,monospace;color:#8d8778;margin-top:4px}
    """

    def esc(t) -> str:
        return html.escape(str(t), quote=False)

    def inline(t: str) -> str:
        s = esc(t.strip())
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    def prose(t: str) -> str:
        out = []
        for para in re.split(r"\n\s*\n", t.strip()):
            if not para.strip():
                continue
            if para.lstrip().startswith("#"):
                out.append(f"<h2>{inline(para.lstrip('# '))}</h2>")
            else:
                out.append(f"<p>{inline(para)}</p>")
        return "".join(out)

    return CSS, esc, inline, prose


@app.cell
def _(Path, mo):
    # A vault is a folder. These are the documents this repo already has, so the
    # notebook is useful before anyone writes a note: sample.md plus the five
    # arXiv abstracts the experiment runs on.
    DOCS = ([Path("sample.md")] if Path("sample.md").exists() else []) + sorted(Path("papers").glob("*.md"))

    # Two signals, deliberately separate: get_doc is what you are reading, get_v
    # is "the log changed, fold it again". An edit bumps the second, so the page
    # cannot confuse "you opened another document" with "a cell changed".
    get_doc, set_doc = mo.state(None)
    get_v, set_v = mo.state(0)
    return DOCS, get_doc, get_v, set_doc, set_v


@app.cell
def _(DOCS, mo, set_doc):
    # The sidebar writes the selection and never reads it; a cell that does both
    # is a cycle, and highlighting the open document is not worth breaking the
    # page for.
    side_items = [
        mo.ui.button(label=d.name, on_click=lambda _v, p=str(d): set_doc(p))
        for d in DOCS
    ]
    mo.sidebar(
        [
            mo.md("### nodus"),
            mo.md("*the document is the map*"),
            mo.vstack(side_items, gap=0.25) if side_items else mo.md("_no documents found_"),
            mo.md("---"),
            mo.md(
                f"{len(DOCS)} documents. This page renders whichever one you pick; edits and "
                "agent proposals live in `solve/delta.jsonl`, keyed by cell id, so they follow "
                "the id rather than the view."
            ),
        ],
        width=230,
    )


@app.cell
def _(mo):
    # Background results arrive as files, so the page re-reads them on a clock.
    # This is the clock, and it is a widget rather than a thread inside the
    # kernel, so nothing runs while you are typing.
    refresh = mo.ui.refresh(options=["5s", "15s", "1m"], default_interval="5s", label="check the queue")
    refresh


@app.cell
def _(DOCS, Path, get_doc, mo, nodus):
    doc_path = Path(get_doc()) if get_doc() else (DOCS[0] if DOCS else None)
    text = doc_path.read_text(encoding="utf-8") if doc_path and doc_path.exists() else ""

    @mo.cache
    def analyse(t: str):
        return nodus.analyse(t, max_gaps=6)

    A = analyse(text)
    # The human layer is what a reader sees: at most five regions merged out of
    # the fine clusters. prune() uses it for the region quota, so a compressed
    # output still shows every region it moved through.
    L = nodus.layers(A) if A.graph.number_of_nodes() >= 4 else None
    return A, L, doc_path, text


@app.cell
def _(cells, delta, get_v, refresh, text):
    # The page is a fold: the document supplies the cells, the log supplies the
    # edits and the proposals. refresh.value and get_v() are read only so that
    # marimo knows this cell must re-run when either changes.
    _ = (refresh.value, get_v())

    doc_cells, proposals = cells.from_log(text, delta.fold_cells())
    sheet = cells.assign(doc_cells + proposals)
    return doc_cells, proposals, sheet


@app.cell
def _(mo):
    budget = mo.ui.slider(200, 4000, value=900, step=100, label="read this much per model output (chars)")
    budget
    return (budget,)


@app.cell
def _(A, L, budget, proposals, prune, text):
    # One budget, split evenly across model outputs. Weighting by length would
    # give the longest, least-read output the most room, which is backwards.
    allocs = prune.allocate(budget.value, len(proposals))
    pruned = {}
    for p_i, p_cell in enumerate(proposals):
        p_gid = p_cell.meta.get("gap")
        p_gap = next((g for g in A.gaps if g.id == p_gid), None)
        pruned[p_cell.id] = prune.prune(
            p_cell.text,
            gap=p_gap,
            analysis=A,
            layers=L,
            corpus=text,
            budget=allocs[p_i],
        )
    return (pruned,)


@app.cell
def _(CSS, A, cells, doc_cells, esc, inline, mo, pruned, prose, proposals):
    def r_header(c) -> object:
        return mo.Html(
            f"<div class='cellhdr'><span><b>{esc(c.id)}</b> \u00b7 {esc(c.origin)} \u00b7 {esc(c.role)}</span>"
            f"<span>{esc(c.view)} \u2014 {esc(c.why)}</span></div>"
        )

    def r_body(c) -> object:
        if c.view == "code":
            return mo.md(f"```\n{c.text}\n```")
        if c.view == "plot":
            return mo.Html(cells.plot_svg(c.text))
        if c.view == "image":
            r_src = c.meta.get("src", "")
            try:
                return mo.image(r_src) if r_src else mo.md("_image cell with no path_")
            except Exception:
                return mo.md(f"_image cell \u2014 `{r_src}` is not on disk_")
        if c.view in ("quote", "claim", "question"):
            return mo.md(f"> {c.text}")
        return mo.Html(f"<div class='doc'>{prose(c.text)}</div>")

    r_parts = [
        mo.Html(
            f"<style>{CSS}</style><div class='nb'><div class='hdr'><b>vault</b>"
            f"<span>{A.summary()['nodes']} concepts \u00b7 {len(A.clusters)} clusters \u00b7 "
            f"{len(A.gaps)} gaps \u00b7 {len(proposals)} proposals</span></div></div>"
        )
    ]

    # Nothing here writes: an edit lands in the log and comes back through the
    # fold, so the page cannot disagree with its own output.
    for r_dc in doc_cells:
        r_parts.append(mo.vstack([r_header(r_dc), r_body(r_dc)], gap=0.1))

    if proposals:
        r_parts.append(mo.md("### what the agents wrote"))

    for r_pc in proposals:
        r_pr = pruned.get(r_pc.id)
        if r_pr is None:
            continue
        if r_pr.nothing:
            r_gist = mo.md("_nothing in this output bears on the gap it was written for_")
        else:
            r_kept = "".join(f"<span class='s'>{inline(k.text)}</span>" for k in r_pr.kept)
            r_gist = mo.Html(f"<div class='out'>{r_kept}</div><div class='meta'>{esc(r_pr.header())}</div>")
        r_crossed = "crosses" if r_pc.meta.get("crossed") else "does not cross"
        r_folded = {
            f"the whole output \u00b7 {len(r_pc.text):,} chars": mo.md(r_pc.text),
        }
        for r_k in r_pr.kept:
            r_folded[f"why {r_k.idx + 1} survived: {r_pr.why(r_k)}"] = mo.md(f"> {r_k.text}")
        if r_pr.dropped:
            r_folded["cut by the budget"] = mo.md("\n\n".join(f"> {k.text}" for k in r_pr.dropped))
        r_parts.append(
            mo.vstack(
                [
                    r_header(r_pc),
                    r_gist,
                    mo.Html(
                        f"<div class='meta'>gap {esc(r_pc.meta.get('gap', '?'))} \u00b7 "
                        f"<span class='chip{' bad' if not r_pc.meta.get('crossed') else ''}'>{r_crossed}</span>"
                        f"<span class='chip{' bad' if not r_pc.meta.get('truth', {}).get('ok') else ''}'>"
                        f"citation {esc(r_pc.meta.get('truth', {}).get('reason', 'not checked'))}</span></div>"
                    ),
                    mo.accordion(r_folded),
                ],
                gap=0.15,
            )
        )
    mo.vstack(r_parts, gap=0.35)
    return


@app.cell
def _(cells, jobs, mo, text):
    # Options come from the document and the job log, never from the folded
    # sheet: that is what keeps this cell independent of the page it edits, so
    # marimo has no cycle to complain about.
    edit_ids = [f"d{i}" for i in range(1, len(cells.blocks(text)) + 1)]
    edit_ids += [j["cell"]["id"] for j in jobs.state().values() if j.get("cell")]
    pick = mo.ui.dropdown(options=edit_ids or ["d1"], value=(edit_ids or ["d1"])[0], label="cell")
    edit_text = mo.ui.text_area(
        rows=4,
        full_width=True,
        label="rewrite it \u2014 your words replace the model's, and the log keeps both",
    )
    apply_btn = mo.ui.button(label="apply edit")
    mo.vstack(
        [
            mo.md("### edit a cell"),
            mo.hstack([pick], align="center"),
            edit_text,
            mo.hstack([apply_btn], align="center"),
            mo.md(
                "*native widgets, no contenteditable: the edit is a file write with an actor, so "
                "`solve/delta.jsonl` records the text it replaced.*"
            ),
        ]
    )
    return apply_btn, edit_text, pick


@app.cell
def _(apply_btn, cells, delta, edit_text, mo, pick, set_v):
    # The action cell writes state and reads none, so it cannot depend on the
    # page. set_v takes an updater rather than reading get_v for the same reason.
    if apply_btn.value and edit_text.value.strip():
        e_txt = edit_text.value.strip()
        e_view, e_why, _e_meta = cells.infer(e_txt)
        delta.append("cell_edit", {"id": pick.value, "text": e_txt, "view": e_view}, actor="human")
        set_v(lambda v: v + 1)
        mo.md(f"`{pick.value}` is now yours \u00b7 view re-inferred: **{e_view}** ({e_why})")
    return


@app.cell
def _(A, jobs, mo, sheet, worker):
    # on_click, not `if button.value`: a value check re-fires on every later
    # re-run of this cell, so clicking "stop" would queue another batch first.
    # Handlers write files only - no marimo state - which also keeps this cell
    # from depending on the page it is queueing work for.
    def q_queue(_v=None):
        for g in [g for g in A.gaps if not g.bridged][:3]:
            jobs.enqueue(g, cells=sheet, ask="bridge this gap", actor="human")

    def q_once(_v=None):
        worker.run_one()

    def q_stop(_v=None):
        jobs.cancel_open()

    queue_top = mo.ui.button(label="queue the top gaps", on_click=q_queue)
    run_here = mo.ui.button(label="run one here (blocks this page)", on_click=q_once)
    stop_btn = mo.ui.button(label="stop what has not started", on_click=q_stop)
    mo.hstack([queue_top, run_here, stop_btn], align="center", gap=0.5)
    return


@app.cell
def _(esc, jobs, mo, refresh):
    _ = refresh.value  # re-read the files on the tick, and only then
    st = jobs.stats()
    job_rows = []
    for j in sorted(st["jobs"].values(), key=lambda x: -x.get("opened", 0))[:6]:
        job_rows.append(
            f"<tr><td>{esc(j['id'])}</td>"
            f"<td class='st-{esc(j['status'])}'>{esc(j['status'])}</td>"
            f"<td>{esc(j.get('term_a') or '')} \u2192 {esc(j.get('term_b') or '')}</td>"
            f"<td>{'crosses' if j.get('crossed') else ''}</td>"
            f"<td>{j.get('ms', '')}</td>"
            f"<td>{esc(j.get('stopped') or j.get('error') or '')}</td></tr>"
        )
    mo.Html(
        f"<div class='strip'><div class='hdr'><b>the queue</b>"
        f"<span>{sum(st['counts'].values())} jobs \u00b7 {st['attempts']}/{st['cap_attempts']} attempts \u00b7 "
        f"lanes {st['cap_lanes']} \u00b7 {esc(st['path'])}</span></div>"
        + (
            "<table><tr><th>job</th><th>status</th><th>gap</th><th></th><th>ms</th><th>stop</th></tr>"
            + "".join(job_rows)
            + "</table>"
            if job_rows
            else "<div class='hint'>nothing queued \u2014 `queue the top gaps` writes jobs, "
            "`python worker.py` runs them in another process, and this strip reads the result. "
            "The page re-reads every 5 seconds; adjust that with the clock above.</div>"
        )
        + "</div>"
    )
    return


if __name__ == "__main__":
    app.run()
