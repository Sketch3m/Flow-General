import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="nodus · issues")


@app.cell
def _():
    import os
    from pathlib import Path

    import marimo as mo

    import issues
    import localmodels

    return Path, issues, localmodels, mo, os


@app.cell
def _(mo):
    # Only overrides live in state. The board itself is recomputed from the
    # sources on every run, so editing a file cannot leave a stale issue behind.
    get_gh, set_gh = mo.state("")
    get_over, set_over = mo.state({})
    return get_gh, get_over, set_gh, set_over


@app.cell
def _(mo):
    doc = mo.ui.file(
        filetypes=[".md", ".txt", ".tex", ".py"],
        multiple=False,
        kind="button",
        label="add a document",
    )
    code_path = mo.ui.text(value=".", label="code path", full_width=True)
    mo.hstack(
        [
            mo.vstack([mo.md("**document**"), doc]),
            mo.vstack([mo.md("**code**"), code_path]),
        ],
        widths=[1, 2],
        align="start",
    )
    return code_path, doc


@app.cell
def _(mo):
    repo = mo.ui.text(
        value="",
        placeholder="owner/name",
        label="github repo",
        full_width=True,
    )
    return (repo,)


@app.cell
def _(mo, os, repo, set_gh):
    # The button lives in its own cell because marimo forbids reading a widget's
    # value in the cell that created it - and the repo field is a different cell.
    pull = mo.ui.button(
        label="import issues",
        on_click=lambda _v: set_gh(repo.value.strip()),
    )
    forget = mo.ui.button(label="forget", on_click=lambda _v: set_gh(""))
    token_note = "token: set" if os.environ.get("GITHUB_TOKEN") else "token: none (60 calls/hr)"
    mo.vstack(
        [
            mo.md(f"**github** · {token_note}"),
            mo.hstack([repo, pull, forget], widths=[3, 1, 1], align="end"),
        ]
    )
    return (pull,)


@app.cell
def _(Path, doc):
    _sample = Path(__file__).with_name("sample.md")
    if doc.value:
        _blob = doc.value[0].contents
        try:
            raw = _blob.decode("utf-8")
        except UnicodeDecodeError:
            raw = _blob.decode("latin-1", errors="replace")
        doc_name = doc.value[0].name
    else:
        raw = _sample.read_text() if _sample.exists() else ""
        doc_name = "sample.md" if _sample.exists() else "no document"
    return doc_name, raw


@app.cell
def _(issues, mo, raw):
    @mo.cache
    def _text_issues(text):
        return issues.from_text(text)

    text_items = _text_issues(raw) if raw.strip() else []
    return (text_items,)


@app.cell
def _(code_path, issues, mo):
    @mo.cache
    def _code_issues(root):
        return issues.from_code(root)

    try:
        code_items = _code_issues(code_path.value.strip() or ".")
        code_err = ""
    except Exception as _e:  # a missing path is information, not a crash
        code_items, code_err = [], f"{type(_e).__name__}: {_e}"
    return code_err, code_items


@app.cell
def _(get_gh, issues, mo, os):
    @mo.cache
    def _gh_issues(repo, _has_token):
        try:
            return issues.from_github(repo, state="all", limit=60), ""
        except issues.GitHubError as _e:
            return [], str(_e)

    if get_gh():
        gh_items, gh_err = _gh_issues(get_gh(), bool(os.environ.get("GITHUB_TOKEN")))
    else:
        gh_items, gh_err = [], ""
    return gh_err, gh_items


@app.cell
def _(code_err, code_items, get_over, gh_err, gh_items, issues, text_items):
    board = issues.merge(text_items, code_items, gh_items)
    _over = get_over()
    for _it in board:
        if _it.id in _over:
            # copy before mutating: the sources are cached, and a status must
            # not leak back into the cache
            _copy = issues.Issue.from_dict(_it.to_dict())
            _copy.status = _over[_it.id]
            board[board.index(_it)] = _copy
    return (board,)


@app.cell
def _(board, code_err, doc_name, gh_err, mo):
    _by = {"text": 0, "code": 0, "github": 0}
    _open = 0
    for _it in board:
        _by[_it.source] = _by.get(_it.source, 0) + 1
        _open += _it.status == "open"
    _lines = [
        "# issues",
        f"{len(board)} cards · {_open} open · text {_by['text']} · code {_by['code']} · github {_by['github']}",
        f"document: `{doc_name}`",
    ]
    if code_err:
        _lines.append(f"**code scan failed** — {code_err}")
    if gh_err:
        _lines.append(f"**github failed** — {gh_err}")
    mo.md("\n\n".join(_lines))
    return


@app.cell
def _(mo):
    sources = mo.ui.multiselect(
        options=["text", "code", "github"],
        value=["text", "code", "github"],
        label="sources",
    )
    states = mo.ui.multiselect(
        options=["open", "solved", "wontfix"],
        value=["open"],
        label="status",
    )
    search = mo.ui.text(placeholder="filter titles, queries, evidence", full_width=True, label="")
    mo.hstack([sources, states, search], widths=[1, 1, 3], align="end")
    return search, sources, states


@app.cell
def _(board, mo, search, sources, states):
    _q = search.value.strip().lower()
    _rows = []
    for _it in board:
        if _it.source not in sources.value or _it.status not in states.value:
            continue
        _blob = " ".join(
            [
                _it.title,
                _it.why,
                _it.ref,
                " ".join(_it.labels),
                " ".join(_it.queries),
                " ".join(_e.text for _e in _it.evidence),
            ]
        ).lower()
        if _q and _q not in _blob:
            continue
        _rows.append(
            {
                "id": _it.id,
                "source": _it.source,
                "status": _it.status,
                "score": _it.score,
                "title": _it.title[:110],
                "labels": ", ".join(_it.labels),
            }
        )

    table = mo.ui.table(
        _rows,
        selection="single",
        pagination=True,
        page_size=12,
        show_data_types=False,
        show_column_summaries=False,
        show_download=False,
        label="",
        hidden_columns=["id"],
        format_mapping={"score": "{:.2f}"},
    )
    mo.vstack([mo.md(f"{len(_rows)} shown"), table])
    return (table,)


@app.cell
def _(board, table):
    _sel = table.value
    if isinstance(_sel, list) and _sel:
        _sel = _sel[0]
    _sid = None
    if isinstance(_sel, dict):
        _cand = _sel.get("id")
        if isinstance(_cand, list) and _cand:
            _sid = _cand[0]
        elif isinstance(_cand, str):
            _sid = _cand
    chosen = next((i for i in board if i.id == _sid), None)
    return (chosen,)


@app.cell
def _(chosen, issues, mo):
    if chosen is None:
        _view = mo.md(
            "*Select a row.* A card is a gap: two parts of something that never meet, "
            "the evidence on both sides, and the search that would close it."
        )
    else:
        _num = ", ".join(
            f"{_k}={_v}"
            for _k, _v in chosen.numbers.items()
            if isinstance(_v, (int, float, str)) and str(_v)
        )
        _ev = "\n".join(
            f"- `{_e.loc or _e.kind}` — {_e.text[:240]}" for _e in chosen.evidence[:6]
        ) or "- (none yet)"
        _queries = "\n".join(
            f"- [{_q}]({issues.search(_q)})" for _q in chosen.queries[:3]
        )
        _src = ""
        if chosen.numbers.get("url"):
            _src = f"\n[ticket]({chosen.numbers['url']})\n"
        _view = mo.md(
            f"## {chosen.title}\n"
            f"`{chosen.source}` · `{'`, `'.join(chosen.labels)}` · score **{chosen.score:.2f}** · "
            f"confidence **{chosen.confidence:.2f}** · `{chosen.loc}`\n\n"
            f"{chosen.why}\n"
            f"{_src}\n"
            f"**numbers** — {_num}\n\n"
            f"**evidence**\n{_ev}\n\n"
            f"**what would settle it** — {chosen.confirm}\n\n"
            f"**search**\n{_queries}"
        )
    _view
    return


@app.cell
def _(chosen, get_over, mo, set_over):
    def _mark(status):
        def _apply(_v):
            _over = dict(get_over())
            _over[chosen.id] = status
            set_over(_over)

        return _apply

    if chosen is None:
        _bar = mo.md("")
    else:
        _bar = mo.hstack(
            [
                mo.ui.button(label="solved", on_click=_mark("solved")),
                mo.ui.button(label="won't fix", on_click=_mark("wontfix")),
                mo.ui.button(label="reopen", on_click=_mark("open")),
                mo.md(f"status: **{chosen.status}**"),
            ],
            align="center",
        )
    _bar
    return


@app.cell
def _(mo):
    save = mo.ui.run_button(label="save board")
    mo.hstack(
        [save, mo.md("*solve/issues.json is gitignored: the board is working state, not source.*")],
        align="center",
    )
    return (save,)


@app.cell
def _(board, issues, save):
    if save.value:
        _p = issues.save(board)
        mo.md(f"saved {len(board)} cards → `{_p}`")
    else:
        mo.md("")
    return


@app.cell
def _(chosen, localmodels, mo):
    _SYSTEM = (
        "You are helping with one gap in a document or a codebase. "
        "Use only the evidence given. If the evidence does not decide the "
        "question, say so in one sentence instead of guessing. Never invent a "
        "quote, a file, or a number."
    )

    def _content(msg):
        c = getattr(msg, "content", "")
        if isinstance(c, str):
            return c
        parts = []
        for p in c or []:
            if isinstance(p, dict):
                parts.append(p.get("text", ""))
            else:
                parts.append(getattr(p, "text", str(p)))
        return " ".join(x for x in parts if x)

    def _model(messages, config):
        if chosen is None:
            return "Select an issue first: the evidence goes into the prompt."
        _ev = "\n".join(f"[{e.loc}] {e.text}" for e in chosen.evidence[:6])
        _ctx = (
            f"Issue: {chosen.title}\nWhy: {chosen.why}\n"
            f"What would settle it: {chosen.confirm}\nEvidence:\n{_ev}"
        )
        _msgs = [{"role": "system", "content": _SYSTEM + "\n\n" + _ctx}]
        _msgs += [{"role": getattr(m, "role", "user"), "content": _content(m)} for m in messages]
        _r = localmodels.chat(_msgs)
        if _r["error"]:
            return (
                f"local model unavailable ({_r['error']}).\n\n"
                "The card is self-contained, so paste this into any chat:\n\n"
                f"```\n{_SYSTEM}\n\n{_ctx}\n```"
            )
        return _r["text"]

    _chat = mo.ui.chat(
        _model,
        prompts=[
            "What would close this gap?",
            "Which piece of evidence is weakest?",
            "What should I search for first?",
        ],
        max_height=320,
    )
    mo.vstack([mo.md("### work on it\n*local Qwen, grounded on the card. Its quotes are not trusted — read them against the evidence above.*"), _chat])
    return


if __name__ == "__main__":
    app.run()
