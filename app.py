import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="nodus")


@app.cell
def _():
    import html
    import json
    import re
    from pathlib import Path

    import networkx
    import marimo as mo

    import corpus
    import decision
    import dialog
    import embark
    import gist
    import nodus
    import ontology
    import orchestrator

    return (
        Path,
        corpus,
        decision,
        dialog,
        embark,
        gist,
        html,
        json,
        mo,
        networkx,
        nodus,
        ontology,
        orchestrator,
        re,
    )


@app.cell
def _(Path, mo):
    _sample = Path(__file__).with_name("sample.md")
    doc = mo.ui.text_area(
        value=_sample.read_text() if _sample.exists() else "",
        rows=12,
        debounce=True,
        label="",
        full_width=True,
    )
    files = mo.ui.file(
        filetypes=[".md", ".txt", ".tex", ".py", ".json"],
        multiple=True,
        kind="button",
        label="add documents",
    )
    budget = mo.ui.slider(300, 12000, value=700, step=100, label="context budget")
    save = mo.ui.run_button(label="save ledger")
    return budget, doc, files, save


@app.cell
def _(doc):
    text = doc.value or ""
    return (text,)


@app.cell
def _(files):
    """Uploaded documents, decoded. The declared type is authoritative; the
    extension is only a hint, so a .tex full of UTF-8 still arrives intact."""
    sources = []
    for _f in files.value:
        _blob = _f.contents
        try:
            _t = _blob.decode("utf-8")
        except UnicodeDecodeError:
            _t = _blob.decode("latin-1", errors="replace")
        sources.append((_f.name, _t))
    return (sources,)


@app.cell
def _(corpus, mo, sources, text):
    @mo.cache
    def _organize(srcs: tuple, one: str):
        return corpus.organize(list(srcs) if srcs else [("document", one)])

    c = _organize(tuple(sources), text)
    return (c,)


@app.cell
def _(dialog, text):
    dlg = dialog.parse(text, name="nodus")
    return (dlg,)


@app.cell
def _(decision, mo):
    get_records, set_records = mo.state(decision.load())
    return get_records, set_records


@app.cell
def _(c, mo):
    get_sel, set_sel = mo.state(None)
    get_map, set_map = mo.state(0)  # 0 closed, 1 corner, 2 full

    # The three gaps the page will show. Chosen here, once, so that every note
    # that is rendered has a button and every button has a note.
    shown = [g for g in c.analysis.gaps if not g.bridged][:3] or c.analysis.gaps[:3]

    # One control per gap, living in the margin note it belongs to. No global
    # toolbar: in a notebook an action belongs to the cell it acts on.
    gap_buttons = {
        g.id: mo.ui.button(label="work on this", on_click=lambda _v, gid=g.id: set_sel(gid))
        for g in shown
    }
    clear_sel = mo.ui.button(label="\u00d7 put it down", on_click=lambda _v: set_sel(None))
    map_open = mo.ui.button(label="\u229e map", on_click=lambda _v: set_map(1))
    map_big = mo.ui.button(label="\u2922 expand", on_click=lambda _v: set_map(2))
    map_small = mo.ui.button(label="\u2212 minimise", on_click=lambda _v: set_map(1))
    map_close = mo.ui.button(label="\u00d7 close", on_click=lambda _v: set_map(0))
    return (
        clear_sel,
        gap_buttons,
        get_map,
        get_sel,
        map_big,
        map_close,
        map_open,
        map_small,
        set_sel,
        shown,
    )


@app.cell
def _(c, get_sel):
    _id = get_sel()
    gap = next((g for g in c.analysis.gaps if g.id == _id), None)
    return (gap,)


@app.cell
def _(c, corpus, dlg, get_records):
    plan = corpus.plan(c, dlg=None, records=get_records())
    return (plan,)


@app.cell
def _(mo):
    claim_text = mo.ui.text(label="claim", placeholder="one sentence", full_width=True)
    claim_source = mo.ui.text(label="source", placeholder="https://…", full_width=True)
    claim_quote = mo.ui.text(label="exact quote", placeholder="the words you rely on", full_width=True)
    claim_status = mo.ui.radio(["supports", "contradicts", "unclear"], value="unclear", label="status")
    add_claim = mo.ui.run_button(label="file claim")
    return add_claim, claim_quote, claim_source, claim_status, claim_text


@app.cell
def _(mo):
    decision_text = mo.ui.text(label="decision", placeholder="what you will do, not what you learned", full_width=True)
    confidence = mo.ui.slider(0.0, 1.0, value=0.5, step=0.05, label="confidence")
    rationale = mo.ui.text_area(label="why", rows=2, full_width=True)
    alts = mo.ui.text_area(label="options weighed — option :: utility :: downside", rows=2, full_width=True)
    next_ev = mo.ui.text_area(label="what would change your mind", rows=2, full_width=True)
    decide = mo.ui.run_button(label="close it")
    return alts, confidence, decide, decision_text, next_ev, rationale


@app.cell
def _(
    add_claim,
    alts,
    budget,
    c,
    claim_quote,
    claim_source,
    claim_status,
    claim_text,
    clear_sel,
    confidence,
    decide,
    decision,
    decision_text,
    dlg,
    doc,
    embark,
    files,
    gap,
    gap_buttons,
    get_map,
    get_records,
    gist,
    html,
    json,
    map_big,
    map_close,
    map_open,
    map_small,
    mo,
    networkx,
    shown,
    next_ev,
    nodus,
    ontology,
    orchestrator,
    plan,
    rationale,
    re,
    save,
    text,
):
    # ---------------------------------------------------------------- styling
    CSS = """
    .nb{--ink:#1d1b18;--mute:#6f6a5f;--line:#e3dfd5;--rule:#eeebe3;--paper:#fbfaf7;
        --acc:#a8442a;--cool:#2b6478;--warm:#f7f0e2;
        max-width:1080px;margin:0 auto;padding:0 20px 140px;
        font-family:ui-serif,Georgia,'Iowan Old Style',serif;color:var(--ink)}
    .nb a{color:var(--cool)}
    .hdr{display:flex;align-items:baseline;gap:12px;padding:14px 0 8px;
        font:11px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:#a09889}
    .hdr b{font:600 13px ui-monospace,monospace;letter-spacing:.14em;color:var(--ink)}
    .hdr{flex-wrap:wrap}
    .hst{font:9.5px ui-monospace,monospace;color:#b3aa9a;margin-left:auto}
    .src{margin-bottom:4px}
    .src summary{font:10px ui-monospace,monospace;letter-spacing:.06em;color:#a09889;
        cursor:pointer;padding:2px 0}
    .src[open] summary{color:var(--acc)}
    .qq{font:11.5px/1.55 ui-monospace,monospace;color:#4a4438;margin:2px 0}
    .qq span{display:inline-block;min-width:60px;font-size:9px;letter-spacing:.08em;
        text-transform:uppercase;color:#a09889}
    .near{margin-top:8px;font:13px/1.5 ui-serif,Georgia,serif;color:#4a4438;
        border-left:2px solid var(--rule);padding-left:9px;max-width:60ch}
    .near>span{display:block;font:9px ui-monospace,monospace;letter-spacing:.08em;
        text-transform:uppercase;color:#a09889;margin-bottom:2px}

    /* a notebook cell: bracket on the left, label in the gutter */
    .cellin,.cellout{display:grid;grid-template-columns:56px 1fr;gap:0;
        margin:0 0 14px;position:relative}
    .cellin{border-top:1px solid var(--line);padding-top:12px}
    .cellout{border-top:1px solid var(--line);padding-top:12px}
    .gutter{padding-top:2px;font:10px ui-monospace,monospace;color:#b3aa9a;
        letter-spacing:.04em;text-align:right;padding-right:10px;user-select:none}
    .cellin .gutter{color:var(--acc)}
    .content{min-width:0;border-left:2px solid var(--rule);padding-left:16px}
    .cellin .content{border-left-color:#e8dcc6}
    .cellin:hover .content{border-left-color:#dcc9a8}

    /* the document, with a margin that holds what the graph noticed */
    .row{display:grid;grid-template-columns:minmax(0,1fr) 208px;gap:18px;
        padding:2px 0 4px}
    .row.wide{grid-template-columns:minmax(0,1fr)}
    .doc{min-width:0;max-width:66ch}
    .note{font-family:ui-sans-serif,system-ui;font-size:12px;line-height:1.45;
        border-left:2px solid #e8dcc6;padding:2px 0 2px 9px;align-self:start;
        margin-top:4px}
    .note.open{border-left-color:var(--acc)}
    .note .nt{font:600 9.5px ui-monospace,monospace;letter-spacing:.09em;
        text-transform:uppercase;color:var(--acc);margin-bottom:3px}
    .note .nb2{color:#4a4438}
    .note .nm{color:#a09889;font:10.5px ui-monospace,monospace;margin-top:3px}
    .note button{font:600 11px ui-sans-serif,system-ui;padding:2px 7px;margin-top:6px;
        border-radius:5px;border:1px solid var(--line);background:#fff;color:var(--ink);
        cursor:pointer}
    .note button:hover{background:var(--warm)}
    .note details{margin-top:5px}
    .note summary{font:10px ui-monospace,monospace;color:#a09889;cursor:pointer}
    .note table{font:10.5px ui-monospace,monospace;margin-top:4px;border-collapse:collapse}
    .note td{padding:1px 0}
    .note td:first-child{color:#a09889;padding-right:8px}

    /* prose */
    .prose p{margin:0 0 .62em;font-size:16.5px;line-height:1.62}
    .prose h2{font-size:18px;margin:.8em 0 .4em;letter-spacing:-.01em}
    .prose h3{font-size:13px;margin:.8em 0 .3em;color:var(--mute);
        text-transform:uppercase;letter-spacing:.08em;font-family:ui-sans-serif,system-ui}
    .tok{border-bottom:2px solid #e8c9a0;background:#fdf7ea;cursor:help}
    .ask{font:11px ui-monospace,monospace;color:var(--acc);text-transform:uppercase;
        letter-spacing:.08em;margin:0 0 4px}
    .gist{background:var(--warm);border-left:3px solid var(--acc);padding:9px 12px;
        font-size:15.5px;line-height:1.6;margin:2px 0 6px}
    sup.chip{font:9.5px ui-monospace,monospace;color:var(--cool);background:#eaf2f6;
        border:1px solid #cfe0e8;border-radius:4px;padding:0 3px;margin-left:3px;
        cursor:help;vertical-align:super;text-decoration:none}
    .meta{font:10.5px/1.5 ui-monospace,monospace;color:#8d8778;margin-top:4px}
    pre.full{white-space:pre-wrap;font:12px/1.55 ui-monospace,monospace;color:#4a4438;
        background:#fff;border:1px solid var(--line);border-radius:6px;padding:9px;
        margin:6px 0 0;max-height:260px;overflow:auto}
    details.more{margin-top:4px}
    details.more summary{font:10.5px ui-monospace,monospace;color:var(--mute);cursor:pointer}

    /* the chosen gap */
    .q{font-size:17px;line-height:1.5;margin:0 0 4px;max-width:60ch}
    .q b{color:var(--acc)}
    .ev{display:flex;gap:14px;flex-wrap:wrap;font:10.5px ui-monospace,monospace;
        color:#8d8778;margin:2px 0 8px}
    .ev i{font-style:normal;color:#4a4438}
    .forms{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;
        font-family:ui-sans-serif,system-ui}
    .forms label{font:9.5px ui-monospace,monospace;letter-spacing:.08em;
        text-transform:uppercase;color:#a09889}
    .w{max-width:340px}

    /* analysis, folded away */
    .analysis{margin:26px 0 0;border-top:1px solid var(--line);padding-top:12px}
    .analysis>summary{font:10.5px ui-monospace,monospace;letter-spacing:.08em;
        text-transform:uppercase;color:#a09889;cursor:pointer}
    .acell{border-left:2px solid var(--rule);padding:2px 0 2px 14px;margin:14px 0}
    .acell h3{margin:0 0 4px;font:600 13.5px ui-sans-serif,system-ui}
    .acell .why{font:10.5px/1.4 ui-monospace,monospace;color:#a09889;margin-bottom:6px}
    .ov{display:flex;gap:16px;flex-wrap:wrap;font-family:ui-sans-serif,system-ui;margin:2px 0 8px}
    .ov b{display:block;font:600 19px/1.1 ui-serif,Georgia,serif}
    .ov span{font:9px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:#a09889}
    .regs{display:flex;gap:6px;flex-wrap:wrap}
    .reg{border:1px solid var(--line);border-radius:7px;padding:5px 7px;background:#fff;
        font:11px ui-sans-serif,system-ui;min-width:120px}
    .reg span{display:block;font:9.5px ui-monospace,monospace;color:#a09889;margin-top:2px}
    .cov{width:100%;border-collapse:collapse;font:11.5px ui-sans-serif,system-ui}
    .cov th{text-align:left;font:9px ui-monospace,monospace;letter-spacing:.08em;
        text-transform:uppercase;color:#a09889;padding:0 8px 3px 0;font-weight:400}
    .cov td{padding:2px 8px 2px 0;border-top:1px dotted var(--line)}
    .cov td.n{font:10.5px ui-monospace,monospace;color:#8d8778;text-align:right}
    .bar{height:5px;border-radius:3px;background:var(--warm);position:relative;min-width:54px}
    .bar i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--cool)}
    .ul{margin:2px 0 0;padding-left:15px;font:12.5px/1.6 ui-sans-serif,system-ui;color:#4a4438}
    .ul code{font:11px ui-monospace,monospace;color:var(--acc)}
    .packet pre{background:#fff;border:1px solid var(--line);border-radius:7px;padding:9px;
        font:11px/1.5 ui-monospace,monospace;max-height:300px;overflow:auto;margin-top:6px}

    /* the map */
    .chipmap{position:fixed;right:16px;bottom:16px;z-index:40}
    .map{position:fixed;right:16px;bottom:16px;width:190px;z-index:40;background:#fffdf8;
        border:1px solid var(--line);border-radius:11px;box-shadow:0 6px 24px rgba(60,50,30,.09);
        padding:8px;font-family:ui-sans-serif,system-ui}
    .map .hd{display:flex;justify-content:space-between;align-items:center;gap:4px;
        font:9px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:#a09889}
    .tl{display:flex;gap:3px;align-items:center}
    .map button,.note button{font:9.5px ui-monospace,monospace;border:1px solid var(--line);
        border-radius:4px;background:#fff;padding:1px 5px;cursor:pointer;color:var(--mute)}
    .map button:hover{background:var(--warm);color:var(--ink)}
    .map .lg{font:9.5px/1.4 ui-monospace,monospace;color:#8d8778;margin-top:4px}
    .grow{position:fixed;inset:3%;z-index:80;background:#fffdf8;border:1px solid var(--line);
        border-radius:13px;box-shadow:0 20px 60px rgba(40,30,10,.22);padding:14px;
        display:flex;flex-direction:column;overflow:auto;font-family:ui-sans-serif,system-ui}
    .grow h3{margin:0;font:10px ui-monospace,monospace;letter-spacing:.1em;
        text-transform:uppercase;color:#a09889}
    .grow .bar2{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
    .grow svg{max-width:100%;height:auto}

    @media (max-width:820px){
      .row{grid-template-columns:minmax(0,1fr)}
      .note{margin-top:6px}
      .cellin,.cellout{grid-template-columns:40px 1fr}
      .forms{grid-template-columns:1fr}
    }
    """

    # ---------------------------------------------------------------- helpers
    def w(x) -> str:
        """A live element as markup. `str(widget)` gives 'button()' - marimo
        needs `_repr_html_()` to hand the runtime a hydratable element."""
        return x._repr_html_() if hasattr(x, "_repr_html_") else str(x)

    def esc(t) -> str:
        return html.escape(str(t), quote=False)

    def inline(t: str, values: dict[str, str]) -> str:
        s = esc(t)
        for raw, val in values.items():
            e = esc(raw)
            s = s.replace(e, f'<span class="tok" title="{esc(val)}">{e}</span>')
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    def prose(t: str, values: dict[str, str]) -> str:
        out = []
        for para in re.split(r"\n\s*\n", t.strip()):
            if not para.strip():
                continue
            if para.lstrip().startswith("#"):
                out.append(f"<h2>{inline(para.lstrip('# ').strip(), values)}</h2>")
            else:
                out.append(f"<p>{inline(para.strip(), values)}</p>")
        return "".join(out)

    def plain(v: str) -> str:
        return re.sub(r"[*`]", "", v)

    A = c.analysis
    gaps = shown

    # ---------------------------------------------------------------- notes
    # A gap is attached to the message that talks about both sides most. That
    # is the whole placement algorithm: no layout model, no model at all, just
    # counting. If it lands on the wrong paragraph a reader can see the count
    # and disagree.
    def attach(d) -> dict[str, list]:
        out: dict[str, list] = {}
        for g in gaps:
            terms = {t for t in g.terms_a[:7]} | {t for t in g.terms_b[:7]}
            best, score = None, 0
            for m in d.messages:
                if m.skipped:
                    continue
                low = m.body.lower()
                hits = sum(low.count(t) for t in terms)
                if hits > score:
                    best, score = m.id, hits
            if best is not None:
                out.setdefault(best, []).append((g, score))
        return out

    def note_html(g, score: int) -> str:
        # The note names the absent pair, not the two cluster labels: the pair is
        # what the evidence is about, and it is a thing a writer can act on.
        a = g.missing[0] if g.missing else (g.terms_a[0] if g.terms_a else "?")
        b = g.missing[1] if g.missing else (g.terms_b[0] if g.terms_b else "?")
        miss = f"clusters {g.terms_a[0]} \u00d7 {g.terms_b[0]}" if g.terms_a and g.terms_b else "no pair"
        hops = (
            f"{g.distance} link{'s' if g.distance != 1 else ''} apart"
            if g.distance is not None
            else "disconnected"
        )
        opened = gap is not None and gap.id == g.id
        button = gap_buttons.get(g.id)
        action = w(button) if button is not None else ""
        typed = ontology.crossings(rels, set(g.terms_a), set(g.terms_b))
        rows = [
            ("absent", f"{g.surprise:.2f}\u03c3 more than chance"),
            ("resource alloc", f"{g.ra:.2f}"),
            ("tension", f"{g.tension:.2f}"),
            ("crosses", f"{g.cross_weight} \u00b7 porosity {g.porosity:.2f}"),
            ("typed links", str(len(typed)) if typed else "none"),
        ]
        table = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
        near = (nearest.get(g.id) or [None])[0]
        if near:
            snippet = near["text"][:96].replace("\n", " ").strip()
            closest = (
                f"<div class='nm'>nearest: \u201c{esc(snippet)}…\u201d</div>"
            )
        else:
            closest = ""
        return (
            f"<div class='note{' open' if opened else ''}'>"
            f"<div class='nt'>gap</div>"
            f"<div class='nb2'>nothing links <b>{esc(a)}</b> to <b>{esc(b)}</b></div>"
            f"<div class='nm'>{esc(miss)} \u00b7 {esc(hops)} \u00b7 {score} hits here</div>"
            f"{closest}"
            f"{action}"
            f"<details><summary>why</summary><table>{table}</table></details>"
            f"</div>"
        )

    notes = attach(dlg) if dlg.messages else {}
    # The statement layer: the sentence nearest the missing link, per gap. Two
    # milliseconds for three gaps on a 556-word document, so it can run on every
    # keystroke and still sit in front of the writer.
    nearest = {g.id: nodus.bridge_candidates(text, A, g, k=1) for g in gaps}
    # The ontology layer: typed relations the text actually states. A gap with
    # zero crossings is a stronger claim than "these words are far apart" - it
    # says nothing in the document asserts how the two sides connect.
    rels = ontology.relations(text, set(A.graph.nodes))

    # ---------------------------------------------------------------- document
    def render_doc(d) -> str:
        rows = []
        for m in d.messages:
            over = embark.overlay(m.body, A)
            vals = {o["raw"]: plain(o["value"]) for o in over}
            if m.skipped:
                continue
            if m.type == "prompt":
                head = "<div class='ask'>asked</div>"
                body = f"{head}<div class='prose'><p>{inline(m.source, vals)}</p></div>"
            elif m.type in ("note", "raw"):
                body = f"<div class='prose'>{prose(m.source, vals)}</div>"
            else:
                body = f"<pre class='full'>{esc(m.source)}</pre>"
            for o in over:
                body += f"<div class='meta'>{esc(plain(o['value']))}</div>"

            if m.reply:
                gi = gist.gist(m.reply, [], [], k=2)
                ok, total = gi.verify(m.reply)
                if gi.chosen:
                    sents = " ".join(
                        f"<span class='sent'>{esc(s.text)}"
                        f"<sup class='chip' title='{esc('matched: ' + (', '.join(s.matched) or 'lead sentence'))}'>"
                        f"{s.id}</sup></span>"
                        for s in gi.chosen
                    )
                    note = (
                        f"<div class='gist'>{sents}</div>"
                        f"<div class='meta'>{len(m.reply):,} chars \u2192 {gi.chars:,} \u00b7 "
                        f"{ok}/{total} citations verified \u00b7 "
                        f"<span title='spans are re-sliced from the source and compared character for character'>"
                        f"quote is real, not that it supports the idea</span></div>"
                    )
                else:
                    note = "<em class='meta'>nothing in this reply bears on the document</em>"
                body += note
                body += (
                    f"<details class='more'><summary>the full reply \u00b7 "
                    f"{len(m.reply):,} chars in the ledger</summary>"
                    f"<pre class='full'>{esc(m.reply)}</pre></details>"
                )
            cell_notes = "".join(note_html(g, s) for g, s in notes.get(m.id, []))
            rows.append(
                f"<div class='row{'' if cell_notes else ' wide'}'>"
                f"<div class='doc'>{body}</div>"
                f"{f'<div>{cell_notes}</div>' if cell_notes else ''}"
                f"</div>"
            )
        return "".join(rows) or "<p class='meta'>nothing written yet</p>"

    # ---------------------------------------------------------------- chosen gap
    def render_gap(g) -> str:
        typed = ontology.crossings(rels, set(g.terms_a), set(g.terms_b))
        a = g.missing[0] if g.missing else (g.terms_a[0] if g.terms_a else "?")
        b = g.missing[1] if g.missing else (g.terms_b[0] if g.terms_b else "?")
        miss = f"{g.terms_a[0]} \u00d7 {g.terms_b[0]}" if g.terms_a and g.terms_b else "none found"
        qs = "".join(
            f"<div class='qq'><span>{esc(q['mode'])}</span>{esc(q['prompt'])}</div>"
            for q in nodus.question_set(g)
        )
        near = (nearest.get(g.id) or [None])[0]
        near_html = (
            f"<div class='near'><span>nearest statement</span>\u201c{esc(near['text'][:220])}\u201d"
            f"<div class='meta'>leans {esc(near['leans'])} \u00b7 closeness {near['closeness']:.2f} \u00b7 "
            f"terms {esc(', '.join(near['terms'][:4]))}</div></div>"
            if near
            else ""
        )
        q = (
            f"<p class='q'>Nothing in this document links <b>{esc(a)}</b> to "
            f"<b>{esc(b)}</b>.</p>"
            f"<div class='meta' style='margin:-2px 0 6px'>clusters {esc(miss)}</div>"
            f"<div class='ev'>"
            f"<span>absent <i>{g.surprise:.2f}\u03c3</i></span>"
            f"<span>RA <i>{g.ra:.2f}</i></span>"
            f"<span>tension <i>{g.tension:.2f}</i></span>"
            f"<span>cross <i>{g.cross_weight}</i></span>"
            f"<span>typed <i>{len(typed)}</i></span>"
            f"<span>{esc(f'{g.distance} links' if g.distance is not None else 'disconnected')}</span>"
            f"</div>"
            + (
                "<div class='qq'><span>relates</span>"
                + "; ".join(
                    f"{esc(r.subject)} {esc(r.kind)} {esc(r.object)}" for r in typed[:2]
                )
                + "</div>"
                if typed
                else "<div class='qq'><span>relates</span>nothing in the text states how these two connect</div>"
            )
            + f"{qs}{near_html}"
        )
        # what the reply already says that bears on it
        body = ""
        for m in reversed([x for x in dlg.messages if x.reply and not x.skipped][:3]):
            gi = gist.gist(m.reply, g.terms_a[:8], g.terms_b[:8], k=2)
            if not gi.chosen:
                continue
            sents = " ".join(
                f"<span class='sent'>{esc(s.text)}<sup class='chip'>{s.id}</sup></span>"
                for s in gi.chosen
            )
            body += (
                f"<div class='meta'>from reply {m.id} \u00b7 {gi.coverage()}</div>"
                f"<div class='gist'>{sents}</div>"
                f"<div class='meta'>{len(m.reply):,} chars \u2192 {gi.chars:,} \u00b7 "
                f"{len(m.reply) - gi.chars:,} held back in the ledger</div>"
            )
        rec = get_records().get(g.id)
        filed = (
            f"<div class='meta'>filed: {len(rec.claims)} claims, "
            f"{'decided' if rec.decision else 'undecided'}</div>"
            if rec
            else ""
        )
        form = (
            f"<div class='forms'>{w(claim_text)}{w(claim_source)}"
            f"{w(claim_quote)}{w(claim_status)}</div>{w(add_claim)}"
            f"<div style='margin-top:8px'>{w(decision_text)}{w(rationale)}{w(alts)}"
            f"{w(next_ev)}<div class='w'>{w(confidence)}</div>{w(decide)}</div>"
        )
        return q + (body or "<div class='meta'>no reply bears on this gap</div>") + filed + form

    # ---------------------------------------------------------------- analysis
    def mini(wd: int, ht: int, labels: bool, pad: int = 12, cap: int = 240) -> str:
        gg = A.graph
        if gg.number_of_nodes() < 2:
            return f"<svg width='{wd}' height='{ht}'></svg>"
        keep = sorted(gg.nodes, key=lambda n: -A.strength.get(n, 0.0))[:cap]
        pos = networkx.spring_layout(gg.subgraph(keep), seed=7, weight="weight", k=0.42)
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        sx = (wd - 2 * pad) / max(1e-9, max(xs) - min(xs))
        sy = (ht - 2 * pad) / max(1e-9, max(ys) - min(ys))
        a_set, b_set = (set(gap.terms_a), set(gap.terms_b)) if gap else (set(), set())
        region = {}
        for h, cl in enumerate(c.layers.human.clusters):
            for n in cl:
                region[n] = h
        hue = ["#a8442a", "#2b6478", "#7a6a2f", "#5b7a52", "#6d5b86", "#a8862a", "#3f6b6a"]

        def xy(n):
            return (
                pad + (pos[n][0] - min(xs)) * sx,
                ht - pad - (pos[n][1] - min(ys)) * sy,
            )

        out = [f"<svg viewBox='0 0 {wd} {ht}' width='{wd}' height='{ht}' style='display:block'>"]
        for u, v in gg.subgraph(keep).edges:
            x1, y1 = xy(u)
            x2, y2 = xy(v)
            out.append(
                f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                "stroke='#e8e3d7' stroke-width='0.7'"
            )
        for n in keep:
            x, y = xy(n)
            if n in a_set:
                fill, r = "#a8442a", 3.6
            elif n in b_set:
                fill, r = "#2b6478", 3.6
            else:
                fill, r = hue[region.get(n, 0) % len(hue)], 2.0
            out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r}' fill='{fill}' opacity='.85'/>")
            if labels and gg.nodes[n]["freq"] >= 3 and r > 2:
                out.append(
                    f"<text x='{x + 5:.1f}' y='{y + 3:.1f}' font-size='10' fill='#7a7365' "
                    f"font-family='ui-monospace,monospace'>{esc(n)}</text>"
                )
        if gap and a_set and b_set:
            pa = [xy(n) for n in gap.terms_a if n in pos]
            pb = [xy(n) for n in gap.terms_b if n in pos]
            if pa and pb:
                ax = sum(p[0] for p in pa) / len(pa)
                ay = sum(p[1] for p in pa) / len(pa)
                bx = sum(p[0] for p in pb) / len(pb)
                by = sum(p[1] for p in pb) / len(pb)
                out.append(
                    f"<line x1='{ax:.1f}' y1='{ay:.1f}' x2='{bx:.1f}' y2='{by:.1f}' "
                    "stroke='#a8442a' stroke-width='1.4' stroke-dasharray='3 3' opacity='.8'/>"
                )
        out.append("</svg>")
        return "".join(out)

    def render_overview(s: dict) -> str:
        stats = [
            (f"{s['docs']:,}", "documents"),
            (f"{s['words']:,}", "words"),
            (f"{s['nodes']:,}", "concepts"),
            (f"{s['clusters']}", "clusters"),
            (f"{s['regions']}", "regions"),
            (f"{s['modularity']:.2f}", "modularity"),
        ]
        strip = "".join(f"<div><b>{v}</b><span>{k}</span></div>" for v, k in stats)
        regs = "".join(
            f"<div class='reg'>{esc(r['label'])}<span>{r['size']} concepts \u00b7 "
            f"{len(r['clusters'])} clusters</span><span>{esc(', '.join(r['terms'][:3]))}</span></div>"
            for r in c.layers.nesting()
        )
        return f"<div class='ov'>{strip}</div><div class='regs'>{regs}</div>"

    def render_coverage(rows: list[dict]) -> str:
        body = "".join(
            f"<tr><td>{esc(r['doc'])}</td><td class='n'>{r['regions']}</td>"
            f"<td class='n'>{r['spread']:.2f}</td>"
            f"<td><div class='bar'><i style='width:{max(4, min(100, r['spread'] * 100)):.0f}%'></i></div></td></tr>"
            for r in rows[:30]
        )
        return (
            "<table class='cov'><tr><th>document</th><th>regions</th><th>spread</th><th></th></tr>"
            + body + "</table>"
        )

    def render_listing(payload) -> str:
        items = []
        for item in payload[:30]:
            if isinstance(item, tuple):
                h, name = item
                label = next((r["label"] for r in c.layers.nesting() if r["region"] == h), h)
                items.append(f"<li><code>{esc(name)}</code> is the only document covering <b>{esc(label)}</b></li>")
            else:
                items.append(f"<li><code>{esc(item)}</code></li>")
        return f"<ul class='ul'>{''.join(items)}</ul>"

    def render_decision(g) -> str:
        rec = get_records().get(g.id) or decision.from_gap(g)
        return mo.md(decision.render_markdown(rec)).text

    RENDER = {
        "overview": render_overview,
        "coverage": render_coverage,
        "witness": render_listing,
        "orphan": render_listing,
        "decision": render_decision,
    }
    analysis_cells = []
    for spec in plan:
        fn = RENDER.get(spec.kind)
        if fn is None:  # gap and ledger cells already have their own places
            continue
        try:
            body = fn(spec.payload)
        except Exception as e:
            body = f"<div class='meta'>could not render: {esc(type(e).__name__)}: {esc(e)}</div>"
        analysis_cells.append(
            f"<div class='acell'><h3>{esc(spec.title)}</h3>"
            f"<div class='why'>{esc(spec.why)}</div>{body}</div>"
        )

    # ---------------------------------------------------------------- page
    state = get_map()
    packet = (
        orchestrator.task_packet(gap, dlg, budget_chars=budget.value, layers=c.layers)
        if gap
        else {}
    )
    summary = c.summary()
    d = summary
    header = (
        f"<div class='hdr'><b>nodus</b><span>{d['docs']} document"
        f"{'s' if d['docs'] != 1 else ''} \u00b7 {d['words']:,} words \u00b7 "
        f"{d['regions']} regions \u00b7 {len(gaps)} unbridged gaps</span>"
        f"<span class='hst'>{esc(d['structure'])} \u00b7 diversity {d.get('diversity', 0):.2f} "
        f"\u00b7 attention {d.get('concentration', 0):.2f} \u00b7 polarity {d.get('polarity', 0):.2f}</span></div>"
    )

    # The source is the input, but it is not the page. Showing 12 rows of raw
    # markdown above the rendered document made the notebook look like an editor
    # with a reader bolted underneath; it is folded, and the reader comes first.
    in1 = (
        f"<div class='cellin'><div class='gutter'>In[1]</div><div class='content'>"
        f"<details class='src'><summary>\u270e source \u00b7 {len(text.split()):,} words</summary>"
        f"{w(doc)}</details>"
        f"<div style='margin-top:6px;display:flex;gap:10px;align-items:center;"
        f"flex-wrap:wrap'>{w(files)}<div style='min-width:220px'>{w(budget)}</div>{w(save)}</div>"
        f"</div></div>"
    )
    out1 = (
        f"<div class='cellout'><div class='gutter'>Out[1]</div>"
        f"<div class='content'>{render_doc(dlg)}</div></div>"
    )

    if gap is not None:
        in2 = (
            f"<div class='cellin'><div class='gutter'>In[2]</div><div class='content'>"
            f"<div class='meta' style='margin-bottom:4px'>working on {esc(gap.id)} \u00b7 "
            f"{w(clear_sel)}</div>{render_gap(gap)}</div></div>"
        )
        out2 = (
            f"<div class='cellout'><div class='gutter'>Out[2]</div><div class='content'>"
            f"<div class='meta'>what an agent would receive for this gap</div>"
            f"<div class='packet'><pre>{esc(json.dumps(packet, indent=1))}</pre></div>"
            f"</div></div>"
        )
    else:
        in2 = (
            f"<div class='cellout'><div class='gutter'>Out[2]</div><div class='content'>"
            f"<div class='meta'>pick a gap in the margin to work on it \u00b7 "
            f"{len(gaps)} open</div></div></div>"
        )
        out2 = ""

    folded = (
        f"<details class='analysis'><summary>the shape behind the page \u00b7 "
        f"{summary['nodes']} concepts, {summary['clusters']} clusters, {summary['regions']} regions"
        f"</summary>{''.join(analysis_cells)}</details>"
    )

    legend = (
        f"{summary['nodes']:,} concepts \u00b7 {summary['regions']} regions"
        if A.graph.number_of_nodes()
        else "no graph"
    )
    if state == 0:
        map_html = f"<div class='chipmap'>{w(map_open)}</div>"
    elif state == 1:
        map_html = (
            f"<aside class='map'><div class='hd'><span>{esc(legend)}</span>"
            f"<span class='tl'>{w(map_big)}{w(map_close)}</span></div>"
            f"{mini(174, 174, labels=False)}"
            f"<div class='lg'>dashed = selected gap<br/>{esc(gap.id) if gap else 'none selected'}</div>"
            f"</aside>"
        )
    else:
        map_html = (
            f"<div class='grow'><div class='bar2'>"
            f"<h3>the document as a graph \u00b7 {esc(legend)}</h3>"
            f"<span class='tl'>{w(map_small)}{w(map_close)}</span></div>"
            f"{mini(980, 620, labels=True, pad=30, cap=520)}"
            f"<div class='lg'>colour = region \u00b7 rust and teal = the two clusters behind "
            f"<b>{esc(gap.id) if gap else '—'}</b></div></div>"
        )

    mo.md(
        f"<style>{CSS}</style><div class='nb'>{header}{in1}{out1}{in2}{out2}{folded}{map_html}</div>"
    )
    return


@app.cell
def _(add_claim, claim_quote, claim_source, claim_status, claim_text, decision, gap, set_records):
    # Writes to the record on disk, then republishes it as state. Deliberately
    # does not read that state, or marimo reports a cycle.
    if add_claim.value and gap is not None and claim_text.value.strip():
        _all = dict(decision.load())
        _r = _all.get(gap.id) or decision.from_gap(gap)
        _r.add_claim(claim_text.value, claim_source.value, claim_quote.value, claim_status.value)
        _all[_r.gap_id] = _r
        decision.save(_all)
        set_records(_all)
    return


@app.cell
def _(alts, confidence, decide, decision, decision_text, gap, next_ev, rationale, set_records):
    if decide.value and gap is not None and decision_text.value.strip():
        _options = []
        for _line in alts.value.splitlines():
            if "::" not in _line:
                continue
            _o, _u, *_rest = [p.strip() for p in _line.split("::")]
            _options.append(
                {"option": _o, "expected_utility": _u, "downside": _rest[0] if _rest else ""}
            )
        _all = dict(decision.load())
        _r = _all.get(gap.id) or decision.from_gap(gap)
        _r.decide(decision_text.value, confidence.value, rationale.value, _options, next_ev.value.splitlines())
        _all[_r.gap_id] = _r
        decision.save(_all)
        set_records(_all)
    return


@app.cell
def _(dlg, save):
    if save.value:
        dlg.save("dialog.ipynb")
    return


if __name__ == "__main__":
    app.run()
