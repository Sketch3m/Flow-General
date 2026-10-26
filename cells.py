"""
cells.py - a sheet where the *language* decides the cell's UI.

The complaint about the last UI was fair: it was a document with panels bolted
on, not a notebook. A notebook cell has always been "a thing that runs", and the
thing it runs is chosen by what is written in it. Here the same rule applies to
prose and images:

    a paragraph                 -> prose
    a paragraph ending in ?     -> a question, with a gap it belongs to
    "the cat crossing the road" -> an image cell, if a path is given
    "predator and prey ..."     -> a Lotka-Volterra plot, drawn from the sentence
    a fence of code             -> code
    $...$ or !gap(a, b)         -> a live formula

Two layers decide, and they are kept apart on purpose:

    infer()        deterministic, 1 ms, always runs, and says why it chose
    choose_view()  the small model chooses among the same closed set of kinds

The model is allowed to *choose a view*, never to invent one: the spec comes from
infer(), so a bad choice costs a wrong widget, not a broken page. That is the
same rule the rest of this repo follows for generated text.

The other half is the part you asked not to see. Every cell's text is fed to the
graph, and the graph's reading of the sheet - which cells are close, which two
never meet, what the nearest bridging statement is - is **latent context**:

    cell.latent  = the links and gaps that involve this cell
    sheet.latent = the whole read, one dict

It is passed to Qwen and deliberately not rendered in the cell. A toggle at the
bottom of the sheet can show it, because a system that hides its own context
completely is a system you cannot debug.

No image tool is installed in this environment, so the image cell renders a path
that already exists on disk, or says what it needs. It does not invent a cat.
"""

from __future__ import annotations

import html
import math
import re
import time
from dataclasses import dataclass, field

import nodus
import ontology

# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

KINDS = ("prose", "question", "claim", "quote", "image", "plot", "formula", "code", "paper")

IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|((?:[\w./-]+)\.(?:png|jpe?g|gif|webp|svg))", re.I)
FENCE = re.compile(r"```")
FORMULA = re.compile(r"!(\w+)\s*\(|\$[^$]+\$|\\frac|\\sum")
QUOTE = re.compile(r"^\s*>\s?|\u201c[^\u201d]+\u201d")
CLAIM = re.compile(r"\b(because|therefore|implies|suggests|leads to|depends on|requires|so that)\b", re.I)
DYNAMIC = re.compile(
    r"\b(predator|prey|population|lotka|volterra|oscillat|dynamics|growth rate|carrying capacity|competing species)\b",
    re.I,
)
PAPER = re.compile(r"^#\s+.*\n.*arXiv:\s*\d{4}\.\d{4,5}", re.S)


@dataclass
class Cell:
    id: str
    text: str
    origin: str = "human"  # human | qwen | nodus
    view: str = ""
    why: str = ""
    role: str = "note"  # note | seed | paper | hypothesis
    meta: dict = field(default_factory=dict)
    latent: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "origin": self.origin,
            "view": self.view,
            "why": self.why,
            "role": self.role,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Cell":
        return cls(**{k: d[k] for k in ("id", "text", "origin", "view", "why", "role", "meta") if k in d})


def infer(text: str) -> tuple[str, str, dict]:
    """Deterministic view inference: kind, why, params. Never raises."""
    t = text.strip()
    if not t:
        return "prose", "empty", {}
    m = IMAGE.search(t)
    if m:
        path = m.group(1) or m.group(2)
        return "image", f"names an image path ({path})", {"src": path}
    if PAPER.match(t):
        aid = re.search(r"arXiv:\s*(\d{4}\.\d{4,5})", t)
        return "paper", "title + arXiv id", {"arxiv": aid.group(1) if aid else ""}
    if FENCE.search(t):
        return "code", "fenced code", {}
    if FORMULA.search(t):
        return "formula", "live formula syntax", {}
    # A question *about* predator and prey is not a predator-prey simulation.
    # Asking first is what keeps the duck's street from becoming a phase plot.
    if t.endswith("?") and len(t) < 400:
        return "question", "ends in a question mark", {}
    if DYNAMIC.search(t):
        return "plot", "predator/prey vocabulary - drawn as Lotka-Volterra", {"model": "lotka_volterra"}
    if QUOTE.match(t):
        return "quote", "quoted passage", {}
    if CLAIM.search(t):
        return "claim", "states a relation (because/therefore/implies/requires)", {}
    return "prose", "no other signal", {}


def assign(cells: list[Cell]) -> list[Cell]:
    for c in cells:
        if not c.view:
            c.view, c.why, c.meta = infer(c.text)
    return cells


def choose_view(text: str, use_qwen: bool = True) -> dict:
    """The model's choice among the same closed set of views.

    It cannot invent a widget: the name is one of KINDS or the deterministic
    answer stands. Whether its choice is *good* is measured separately, because
    "qwen chose a plot for the duck" is a result, not an exception.
    """
    base = infer(text)[0]
    if not use_qwen:
        return {"view": base, "by": "rules", "ms": 0, "error": "qwen disabled"}
    import localmodels

    t0 = time.time()
    r = localmodels.pick(
        "Which widget should this cell become?",
        list(KINDS),
        context=text[:400],
    )
    pick = r["choice"] if r["choice"] in KINDS else base
    return {"view": pick, "by": "qwen" if pick != base else "agree", "ms": int((time.time() - t0) * 1000), "error": r["error"]}


# ---------------------------------------------------------------------------
# the two views that need drawing
# ---------------------------------------------------------------------------

_PARAMS = dict(alpha=1.1, beta=0.4, delta=0.1, gamma=0.9, prey=10.0, pred=5.0)


def lotka_volterra(prey: float = 10.0, pred: float = 5.0, steps: int = 400, dt: float = 0.02):
    """Deterministic RK2 integration; returns two series. No plotting library."""
    a, b, d, g = _PARAMS["alpha"], _PARAMS["beta"], _PARAMS["delta"], _PARAMS["gamma"]
    x, y = prey, pred
    xs, ys = [], []
    for _ in range(steps):
        dx = a * x - b * x * y
        dy = d * x * y - g * y
        xm, ym = x + dx * dt / 2, y + dy * dt / 2
        dx2 = a * xm - b * xm * ym
        dy2 = d * xm * ym - g * ym
        x, y = max(0.0, x + dx2 * dt), max(0.0, y + dy2 * dt)
        xs.append(x)
        ys.append(y)
    return xs, ys


def sparkline(series: list[float], w: int = 520, h: int = 150, colour: str = "#2f7d5d") -> str:
    if not series:
        return ""
    lo, hi = min(series), max(series)
    rng = (hi - lo) or 1.0
    pts = " ".join(
        f"{i * w / (len(series) - 1):.1f},{h - (v - lo) / rng * (h - 12) - 6:.1f}"
        for i, v in enumerate(series)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" role="img">'
        f'<polyline fill="none" stroke="{colour}" stroke-width="2" points="{pts}"/></svg>'
    )


def plot_svg(cell_text: str = "") -> str:
    """A real Lotka-Volterra picture, with the sentence's own numbers if any."""
    nums = [float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", cell_text)[:2]]
    prey, pred = (nums[0], nums[1]) if len(nums) == 2 else (_PARAMS["prey"], _PARAMS["pred"])
    xs, ys = lotka_volterra(prey, pred)
    return (
        '<div class="nodus-plot">'
        + sparkline(xs)
        + sparkline(ys, colour="#b4552d")
        + f'<div class="nodus-plot-cap">prey {prey:g} · predator {pred:g} · '
        "Lotka–Volterra, α 1.1 β 0.4 δ 0.1 γ 0.9</div></div>"
    )


# ---------------------------------------------------------------------------
# latent context: what the graph sees, and the reader does not
# ---------------------------------------------------------------------------


def read(cells: list[Cell], max_gaps: int = 6) -> dict:
    """The sheet as a graph: per-cell concepts, links, and the gaps between them."""
    visible = [c for c in cells if c.text.strip()]
    text = "\n\n".join(c.text for c in visible)
    if len(text.split()) < 40:
        return {"gaps": [], "links": [], "summary": {"words": len(text.split())}}
    a = nodus.analyse(text, max_gaps=max_gaps)
    terms = {c.id: [t for t in nodus.concepts(c.text) if t in a.graph] for c in visible}

    links = []
    for i, ca in enumerate(visible):
        for cb in visible[i + 1 :]:
            shared = sorted(set(terms[ca.id]) & set(terms[cb.id]))
            if shared:
                links.append(
                    {
                        "a": ca.id,
                        "b": cb.id,
                        "shared": shared[:6],
                        "n": len(shared),
                        "weight": round(len(shared) / max(1, len(set(terms[ca.id]) | set(terms[cb.id]))), 3),
                    }
                )
    links.sort(key=lambda d: -d["n"])

    owner = {n: i for i, cl in enumerate(a.clusters) for n in cl}
    gaps = []
    for g in a.gaps:
        if g.bridged:
            continue
        gaps.append(
            {
                **g.to_dict(),
                "where": {
                    c.id: sorted({owner[t] for t in terms[c.id] if t in owner})[:2] for c in visible
                },
            }
        )
    return {
        "gaps": gaps,
        "links": links[:8],
        "summary": a.summary(),
        "discourse": a.discourse.to_dict() if a.discourse else {},
        "analysis": a,
        "terms": terms,
    }


def latent_for(cells: list[Cell]) -> list[Cell]:
    """Attach each cell's slice of the read. Hidden in the UI, present in prompts."""
    r = read(cells)
    a = r.get("analysis")
    for c in cells:
        mine = [g for g in r["gaps"] if any(c.id in w for w in [g["where"]])][:2]
        near = [l for l in r["links"] if c.id in (l["a"], l["b"])][:3]
        c.latent = {
            "terms": r.get("terms", {}).get(c.id, [])[:8],
            "links": near,
            "gaps": [{"id": g["id"], "score": g["score"], "question": g["question"]} for g in mine],
        }
    return cells


# ---------------------------------------------------------------------------
# the agent chain: needle decides, qwen drafts, nodus makes the cell
# ---------------------------------------------------------------------------

ACTIONS = [
    {
        "name": "draft",
        "description": (
            "Write the missing link as one sentence for a new cell. Triggers: write, "
            "add, bridge, connect, hypothesise, propose, explain."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "one side of the gap"},
                "b": {"type": "string", "description": "the other side"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "ask",
        "description": "Ask the human which gap they mean. Triggers: which, choose, unclear, two options.",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
    },
    {
        "name": "stop",
        "description": "Do nothing: the sheet has no unbridged gap or the request is off-topic.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]

DRAFT_SYSTEM = (
    "You write one sentence that links two research areas. Rules: name both areas; "
    "use a relation verb (causes, implies, requires, depends on, supports, contradicts); "
    "say only what the evidence supports; if the evidence is insufficient, start the "
    "sentence with 'However,' and say what is missing. Never invent a paper, a number, "
    "or a quote. One sentence, under 35 words."
)
# The live values moved to harness.py - Qwen may edit them, nodus gates the edit.
# The name above stays as the documented default; draft() reads the live harness.


def card(gap: dict, seed: str, latent: dict) -> str:
    """The flat text Needle grounds on - every field in words, not structure."""
    gap_dir = gap.get('term_a', '?')
    gap_dir += " to "
    gap_dir += gap.get('term_b', '?')
    return (
        f"Cell sheet. Human direction: {gap_dir}. "
        f"Gap: {gap.get('term_a', '?')} to {gap.get('term_b', '?')}, score {gap.get('score', 0):.2f}. "
        f"Latent links: {len(latent.get('links', []))}. "
        "Action: draft one sentence into a new cell."
    )


def decide(gap: dict, seed: str, latent: dict, use_needle: bool = True) -> dict:
    """Needle's three-way routing, with the deterministic answer as the floor.

    Reads both the dispatched call and the held-back suppressed_call.
    `act` comes from the dispatched call (what the model ships).
    `selection` comes from the suppressed_call (what the floor held back).
    """
    t0 = time.time()
    if use_needle:
        try:
            import localmodels

            r = localmodels.route(card(gap, seed, latent), tools=ACTIONS)
            dispatched = r.get("call") or {}
            suppressed = r.get("suppressed_call") or {}
            dname = (dispatched.get("name") or "ask").lower()
            sname = (suppressed.get("name") or "").lower()

            # act: what the model was confident enough to ship
            if dname in ("draft", "stop"):
                act = dname
            else:
                act = "ask"

            # selection: what the model would choose if the floor were removed
            if sname in ("draft", "stop"):
                sel = sname
            elif sname == "ask" and act == "draft":
                # When the floor suppresses draft but the model would ask,
                # selection is ask only if nothing drafts
                sel = "ask"
            else:
                sel = "none"

            conf = round(float(r.get("confidence") or 0.0), 3)
            reason_base = (r.get("reasoning") or "")[:120]
            reason = f"{reason_base} | sel={sel} act={act}"
            return {
                "action": {"draft": "draft", "stop": "stop"}.get(act, "ask"),
                "confidence": conf,
                "reason": reason,
                "ms": int((time.time() - t0) * 1000),
                "by": "needle",
                "selection": sel,
            }
        except Exception as e:  # a missing binary must not break the sheet
            return {"action": "ask", "confidence": 0.0, "reason": f"needle unavailable: {e}", "ms": 0, "by": "fallback"}
    return {"action": "draft", "confidence": 1.0, "reason": "deterministic policy", "ms": 0, "by": "rules"}


def draft(gap: dict, evidence: list[str], use_qwen: bool = True, nudge: str = "") -> dict:
    """Qwen writes the sentence, given the card and the latent context."""
    # Small named groups plus a literal opening clause. Dumping all 15 terms per
    # side made the model echo lists; one head per side made it name only one side,
    # and every relation ended inside one cluster. The first clause pins subject
    # in group one and object in group two (accept()'s crossing test); the two
    # extra words are what accept()'s two-terms-per-side grounding needs.
    ga = gap.get("group_a") or [gap.get("term_a", "")]
    gb = gap.get("group_b") or [gap.get("term_b", "")]
    extra_a = ga[1] if len(ga) > 1 else ga[0]
    extra_b = gb[1] if len(gb) > 1 else gb[0]
    prompt = (
        f"Group one: {', '.join(ga)}\n"
        f"Group two: {', '.join(gb)}\n"
        f"Start the sentence with exactly these words: '{ga[0]} requires {gb[0]} because'. "
        f"Continue with one fact from the evidence and also use the words {extra_a} and {extra_b}. "
        "Do not list words. Do not start with 'However'.\n"
        "Evidence:\n" + "\n".join(f"- {e[:220]}" for e in evidence[:3])
    )
    t0 = time.time()
    if not use_qwen:
        return {"text": "", "error": "qwen disabled", "ms": 0}
    import harness
    import localmodels

    if harness.HARNESS.get("draft_hint"):
        prompt += "\n" + harness.HARNESS["draft_hint"]
    if nudge:
        # Retry feedback: with temp 0.2 an unchanged prompt repeats the same
        # completion, so a resample must say what the last attempt got wrong.
        prompt += "\n" + nudge
    r = localmodels.chat(
        [{"role": "system", "content": harness.HARNESS.get("draft_system", DRAFT_SYSTEM)}, {"role": "user", "content": prompt}],
        max_tokens=80,
        timeout=60,
        stop=["\n"],
    )
    return {"text": (r["text"] or "").strip(), "error": r["error"], "ms": int((time.time() - t0) * 1000)}


def evidence_for(gap: dict, a: nodus.Analysis, text: str, k: int = 2) -> list[str]:
    """The nearest real sentences on both sides - never written by a model."""
    out = []
    g = next((x for x in a.gaps if x.id == gap.get("id")), None)
    if g is not None:
        out += [b["text"][:240] for b in nodus.bridge_candidates(text, a, g, k=k)]
    return out


def accept(terms_a, terms_b, nodes, new_text: str) -> dict:
    """Did the new sentence *state* a relation across the divide? Checked, not judged.

    This is the only test that counts, and it is deliberately easy to pass with a
    false sentence and impossible to pass with a true one that never says "because"
    or "requires". That asymmetry is the reason the experiment reports both the
    pass rate and the text that passed.
    """
    rels = ontology.relations(new_text, set(nodes))
    crossed = [r.to_dict() for r in ontology.crossings(rels, set(terms_a), set(terms_b))]
    # Knowledge, not syntax: the sentence must reuse corpus vocabulary from BOTH
    # sides of the gap. A six-token '<a> implies <b>' has a relation and no grounding.
    lemmas = set(nodus.concepts(new_text))
    side_a = lemmas & set(terms_a)
    side_b = lemmas & set(terms_b)
    # Two terms per side: one shared word on each side is what '<a> implies <b>' has.
    grounded = len(side_a) >= 2 and len(side_b) >= 2
    return {
        "relations": [r.to_dict() for r in rels],
        "crossing": crossed,
        "grounded": grounded,
        "ok": bool(crossed) and grounded,
    }


def pick_direction(questions: list[str], gap: dict, use_qwen: bool = True) -> dict:
    """Closed-set choice: which of the three questions should this cell answer?

    The 0.5B model is good at exactly this and bad at prose, so the direction is
    the model's decision and the sentence is not.
    """
    t0 = time.time()
    if not use_qwen:
        return {"choice": questions[0], "index": 0, "ms": 0, "error": "qwen disabled"}
    import localmodels

    r = localmodels.pick(
        f"Which question best addresses the gap between {gap.get('term_a')} and {gap.get('term_b')}?",
        questions,
        context=f"Gap score {gap.get('score', 0):.2f}. Direction should add something the papers do not say.",
    )
    choice = r["choice"] or questions[0]
    return {"choice": choice, "index": questions.index(choice) if choice in questions else 0, "ms": int((time.time() - t0) * 1000), "error": r["error"]}


def pick_span(spans: list[str], direction: str, use_qwen: bool = True) -> dict:
    """Which existing sentence comes closest to answering the direction?

    Closed set by index, so the answer cannot be a paraphrase - the sentence kept
    in the cell is the one that was in the paper, byte for byte.
    """
    if not spans:
        return {"index": None, "span": "", "ms": 0, "error": "no spans"}
    if not use_qwen:
        return {"index": 0, "span": spans[0], "ms": 0, "error": "qwen disabled"}
    import localmodels

    t0 = time.time()
    opts = [f"span {i + 1}" for i in range(len(spans))]
    r = localmodels.pick(
        f"Which span best answers: {direction}",
        opts,
        context="\n".join(f"span {i + 1}: {s[:220]}" for i, s in enumerate(spans)),
    )
    idx = opts.index(r["choice"]) if r["choice"] in opts else 0
    return {"index": idx, "span": spans[idx], "ms": int((time.time() - t0) * 1000), "error": r["error"]}


DRAFT_TRIES = 3

# Hub glue: words that head some gap ids ('across~record') but cannot head a
# relation. Asking a 0.5B model to use them yields 'across requires record' or a
# missing-term failure, never a crossing.
GLUE = frozenset({
    "across", "about", "after", "before", "between", "during", "through", "within",
    "without", "against", "among", "toward", "towards", "under", "above", "below",
    "along", "around", "because", "these", "those", "their", "there", "which",
    "while", "where", "when", "what", "than", "them", "other", "more", "most",
    "some", "such", "only", "also", "just", "still", "even", "ever",
})


def representatives(terms: list[str], k: int = 3) -> list[str]:
    """Words to put in front of the model: contentful cluster terms, not glue.

    terms_a[0] heads the gap id but is often a preposition. Prefer members that
    can be a subject or object; fall back to the raw order if every term is glue.
    """
    contentful = [t for t in terms if t not in GLUE and len(t) >= 4]
    return (contentful or list(terms))[:k]


def satisfies(text: str, group_a, group_b, nodes) -> tuple[bool, str]:
    """Pre-filter for a draft: both sides named, a relation stated.

    Weaker than accept() on purpose - accept() also needs two terms per side
    and the relation to straddle the gap. This only decides whether the attempt
    is worth sending to accept(). Strings still work as one-term groups.
    """
    if not text.strip():
        return False, "empty"
    a = {group_a} if isinstance(group_a, str) else set(group_a)
    b = {group_b} if isinstance(group_b, str) else set(group_b)
    lemmas = set(nodus.concepts(text))
    if not (lemmas & a):
        return False, f"missing {', '.join(sorted(a)[:3])}"
    if not (lemmas & b):
        return False, f"missing {', '.join(sorted(b)[:3])}"
    if not ontology.relations(text, set(nodes)):
        return False, "no relation verb"
    return True, "ok"


def _nudge_for(why: str, group_a: list[str], group_b: list[str]) -> str:
    """What the loop tells the model after a rejected attempt.

    Each nudge answers the specific failure: an ungrounded crossing is told
    which two words were missing, a non-crossing relation is given the literal
    opening clause, a missing group is quoted back verbatim.
    """
    if why == "crosses, not grounded":
        a2 = group_a[1] if len(group_a) > 1 else group_a[0]
        b2 = group_b[1] if len(group_b) > 1 else group_b[0]
        return f"Your last sentence crossed but was missing a second word: add {a2} and {b2} to it."
    if why == "relation does not cross":
        return f"Begin with exactly these words: '{group_a[0]} requires {group_b[0]} because'."
    if why.startswith("missing"):
        return f"Your last sentence was missing: {why.removeprefix('missing ')}. Include those exact words."
    if why == "no relation verb":
        return f"Put the verb 'requires' between {group_a[0]} and {group_b[0]}."
    return ""


def edit(cells: list[Cell], cell_id: str, text: str) -> list[Cell]:
    """Replace one cell's text and re-infer its view. Other cells are untouched.

    Raises KeyError for an unknown id, so a typo in the editor cannot silently
    create or drop a cell.
    """
    target = next((c for c in cells if c.id == cell_id), None)
    if target is None:
        raise KeyError(cell_id)
    target.text = text
    target.view, target.why, target.meta = infer(text)
    return cells


def sheet_text(cells: list[Cell]) -> str:
    return "\n\n".join(c.text for c in cells if c.text.strip())


def step(cells: list[Cell], mode: str = "draft", use_needle: bool = True, use_qwen: bool = True, sink=None, target: str | None = None, truth_gate: bool = False) -> dict:
    """One turn of the chain: nodus finds, needle decides, qwen points, nodus builds.

    mode="draft"  qwen writes the sentence (fast, fluent, mostly vacuous)
    mode="quote"  qwen picks one real sentence (slow to close a gap, never invents)

    truth_gate=True  block a draft whose cited spans are not in the corpus
    (the quote verdict is computed and logged either way; blocking is opt-in
    so the harness probe and older runs keep comparable numbers)

    sink(kind, payload, actor) receives the latent control events - needle's
    routing and nodus's verdict, with the gap they observed. Nothing is shown
    to the reader; the log is where the hidden decisions stay walkable.
    Callers without a sink (tests, headless scripts) get the same analysis and
    no file writes.

    The returned dict is the log the UI shows, because "the model did something"
    is not an observation - the action, confidence and milliseconds are.
    """
    latent_for(cells)
    r = read(cells)
    a = r.get("analysis")
    if a is None:
        return {"stopped": "not enough text to analyse", "log": []}
    gaps = [g for g in a.gaps if not g.bridged]
    if not gaps:
        return {"stopped": "no unbridged gaps", "log": []}

    # target lets a planned lane attack a specific gap; unknown target falls
    # back to the top gap rather than failing the lane
    gap = gaps[0]
    if target:
        gap = next((g for g in gaps if g.id == target), gaps[0])
    reps_a = representatives(gap.terms_a)
    reps_b = representatives(gap.terms_b)
    gapdict = {
        **gap.to_dict(),
        "term_a": reps_a[0],
        "term_b": reps_b[0],
        "group_a": reps_a,
        "group_b": reps_b,
    }
    seed = next((c.text for c in cells if c.role == "seed"), "")
    d = decide(gapdict, seed, cells[0].latent if cells else {}, use_needle)
    log = [f"nodus   gap {gap.id} score {gap.score:.3f} ({len(gaps)} unbridged)",
           f"needle  {d['action']} @ {d['confidence']:.2f} in {d['ms']} ms - {d['reason'][:90]}"]
    if sink:
        sink("control", {"who": "needle", "action": d["action"], "confidence": d["confidence"], "gap": gap.id}, d.get("by", "needle"))
    if d["action"] == "stop":
        return {"stopped": "needle said stop", "log": log}
    if d["action"] == "ask":
        # No human is sitting in the loop when this runs headless. The ask is
        # recorded, not obeyed; the deterministic policy takes the top gap.
        log.append("policy  no human present: proceed with the top gap")

    text = sheet_text(cells)
    # Representatives, not the raw heads: the head can be a preposition, and a
    # question built from 'across' reads as noise to both the model and the reader.
    qa, qb = reps_a[0], reps_b[0]
    questions = [
        f"What does {qa} imply that these papers have not said yet?",
        f"What is missing between {qa} and {qb}?",
        f"What would connect {qa} to {qb}?",
    ]
    direction = pick_direction(questions, gapdict, use_qwen)
    log.append(f"qwen    direction: {direction['choice'][:90]} ({direction['ms']} ms)")

    spans = [b["text"][:300] for b in nodus.bridge_candidates(text, a, gap, k=3)]
    chosen = pick_span(spans, direction["choice"], use_qwen) if spans else {"span": "", "index": None, "ms": 0}
    evidence = spans[:3]

    acc = None
    if mode == "quote" and chosen["span"]:
        body = f"> {chosen['span']}\n\nDirection: {direction['choice']}"
        origin = "qwen-pick"
        log.append(f"qwen    span {chosen['index'] + 1 if chosen['index'] is not None else '-'} of {len(spans)} ({chosen['ms']} ms)")
    else:
        # Resample until a draft passes accept(), not merely satisfies().
        # satisfies() is the cheap pre-filter (both groups named, a verb present);
        # the gap only closes when the relation straddles AND both sides are
        # grounded, so a pre-filter pass gets its own accept check and, failing
        # that, another attempt. A pre-filter pass with no crossing is kept only
        # as the visible failure it is.
        import harness

        tries = harness.HARNESS.get("draft_tries", DRAFT_TRIES)
        body, origin = "", "qwen-draft"
        fallback = ""
        nudge = ""
        for attempt in range(1, tries + 1):
            wrote = draft(gapdict, evidence, use_qwen, nudge)
            ok, why = satisfies(wrote["text"], reps_a, reps_b, a.graph.nodes)
            if ok and not fallback:
                fallback = wrote["text"]
            if ok:
                trial = accept(gap.terms_a, gap.terms_b, a.graph.nodes, wrote["text"])
                if trial["ok"]:
                    why, acc = "closes the gap", trial
                    body = wrote["text"]
                elif trial["crossing"]:
                    why = "crosses, not grounded"
                else:
                    why = "relation does not cross"
            log.append(f"qwen    sentence {attempt}/{tries} {wrote['ms']} ms - {why}: {wrote['text'][:70] or wrote['error']}")
            if body:
                break
            nudge = _nudge_for(why, reps_a, reps_b)
        if not body and fallback:
            body = fallback

    if not body.strip():
        return {"stopped": "qwen produced nothing", "log": log, "gap": gapdict}

    if acc is None:
        acc = accept(gap.terms_a, gap.terms_b, a.graph.nodes, body)
    state = (
        "crosses"
        if acc["ok"]
        else ("crosses, not grounded" if acc["crossing"] else "no typed relation crosses")
    )
    log.append(f"check   {state} - {[r['kind'] for r in acc['crossing']]}")
    if sink:
        sink(
            "control",
            {"who": "nodus", "gap": gap.id, "crossed": acc["ok"], "grounded": acc["grounded"], "kinds": [r["kind"] for r in acc["crossing"]]},
            "nodus",
        )

    # The quote gate: can this claim point at the corpus? Evaluated on every
    # draft so the log is honest about grounding either way; it only *blocks*
    # when truth_gate is on, keeping the harness probe and older runs
    # comparable. Paper cells are the evidence when the sheet has them.
    import truth

    corpus = sheet_text([c for c in cells if c.role == "paper" or c.origin == "paper"]) or sheet_text(cells)
    verdict = truth.gate(body, corpus)
    log.append(f"gate    {'pass' if verdict['ok'] else 'blocked'} - {verdict['reason']}")
    if not verdict["ok"] and truth_gate:
        if sink:
            sink("control", {"who": "truth", "gap": gap.id, "blocked": True, "reason": verdict["reason"]}, "truth")
        return {"stopped": f"truth gate: {verdict['reason']}", "log": log, "gap": gapdict}

    cell = Cell(id=f"c{len(cells) + 1}", text=body, origin=origin, role="hypothesis")
    assign([cell])
    cell.meta["gap"] = gap.id
    cell.meta["direction"] = direction["choice"]
    cell.meta["crossed"] = acc["ok"]
    cell.meta["truth"] = verdict
    return {"cell": cell, "gap": gapdict, "accept": acc, "direction": direction, "log": log}
