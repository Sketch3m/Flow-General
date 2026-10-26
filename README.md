# nodus — a document that is also a map of itself

| file | what it is | lines |
|---|---|---|
| `nodus.py` | text → concept graph → clusters → ranked gaps, at two resolutions | 985 |
| `corpus.py` | many documents in, one graph, one **ordered page** out | 277 |
| `gist.py` | statements, offset-stable citations, the idea filter | 173 |
| `dialog.py` | SolveIt's dialogue model, with compression instead of eviction | 436 |
| `embark.py` | detectors, formulas, views — the deterministic overlay | 210 |
| `compass.py` | suggested next moves, with truthful distances | 105 |
| `orchestrator.py` | gap → agent task packet, and the ranked queue | 140 |
| `decision.py` | the record a gap becomes: alternatives, confidence, citations | 221 |
| `ontology.py` | typed relations from cue patterns, and whether any crosses a gap | 133 |
| `truth.py` | the quote-the-evidence gate: cited spans must exist in the corpus | 83 |
| `controller.py` | the always-on loop: policy, acceptance test, stopping rules | 268 |
| `localmodels.py` | Needle router + Qwen classifier/chat clients, with their measured limits written down | 277 |
| `bench.py` | reproduces the model numbers below; no keys, no network | 152 |
| `eval_route.py` | three routers on 20 labeled cards: act vs selection, format, forced floor | 238 |
| `eval_native.py` | needle on its own seat: task cards from real gaps, natural/forced/named | 123 |
| `issues.py` | one **Issue** object from three graphs: document, code tree, GitHub tickets | 715 |
| `board.py` | the marimo issue board: import, filter, evidence, search, status, local chat | 385 |
| `cells.py` | cells whose view is inferred from their language; latent graph context; needle→qwen chain | 697 |
| `sheet.py` | the marimo **cell sheet**: per-cell widgets, hidden latent context, run-one-round | 346 |
| `vault.py` | the marimo **vault**: sidebar of documents, real cells, native edits, queue strip | 364 |
| `prune.py` | what a reader may skip: cited + gap-relevant + region quota, then a page budget | 291 |
| `jobs.py` | the gap queue: caps borrowed from `plan.py`, a claim lock, status as a fold | 264 |
| `worker.py` | drains the queue in another process; its proposals land in the delta log | 133 |
| `bridge.py` | the five-paper experiment, with a template control that closes gaps without a model | 232 |
| `experiment.md` | what the loop did, round by round, verbatim | 106 |
| `papers/` | five arXiv abstracts fetched 2026-10-22, the corpus for the experiment | 5 files |
| `app.py` | the page: notebook cells, margin notes, map, decision form | 854 |
| `SOURCES.md` | the papers and tools, with peer-review status and what is only an analogy | 107 |
| `test_issues.py` | adapters tested offline, including the GitHub parser with an injected fetcher | 207 |
| `test_prune.py`, `test_jobs.py` | the three pruning policies and the queue's caps, claim and folds | 133 + 159 |

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/marimo run app.py   --host 0.0.0.0 --port 3000 --no-token   # the document
.venv/bin/marimo run board.py --host 0.0.0.0 --port 3000 --no-token   # the issue board
.venv/bin/marimo run vault.py --host 0.0.0.0 --port 3000 --no-token   # documents + queue
.venv/bin/python worker.py --watch                                    # background agents
.venv/bin/python -m unittest discover -p "test_*.py"
```

## The vault: a folder of documents, one notebook, and a queue

`vault.py` is the page where the three requests meet, and it is deliberately
small: it reads documents, renders cells, and folds a log.

```
sidebar       every .md in sample.md + papers/          one page, any document
cell          In: the document's own paragraph          Out: the widget its
              Out: prose, question, claim, plot, code       language asks for
model output  compressed by `prune.py`                  "1/9 statements · 340/2,180
                                                          chars · 1 cited · 2 regions"
edit          native text_area + apply                   `cell_edit` with actor=human
queue         `python worker.py` in another process      job_done + cell_add, read
                                                          back on a 5 s refresh
```

**The page is a fold, not a widget tree.** `cells.from_log(text, delta.fold_cells())`
returns the document's cells plus whatever the log added; a human edit wins over
the document's text and its view is re-inferred. That is what lets a worker in
a different process add a cell that the page then shows: the shared state is
`solve/delta.jsonl`, not the kernel.

**Compression is graph-weighted, three ways, then budgeted.** A sentence survives
if it quotes the corpus (`truth.find`), or names terms on both sides of a gap, or
is the best sentence on a region the output passed through — and then the page
budget cuts the union by score, so a cited sentence is the last thing dropped,
never the first. Every cut statement is listed under one disclosure: dropped is
not deleted, and the header says how much was withheld.

**The queue borrows its caps instead of inventing them.** `jobs.py` refuses a
fourth lane and a tenth attempt because `plan.py` argued for 3 and 9; it writes
the sheet snapshot with the job, so a worker can rebuild exactly the cells the
human was looking at. `worker.py` claims one job under a lock file, runs
`cells.step` with the citation gate *evaluated but not blocking* (drafts quote
nothing, so blocking would empty the queue and hide the finding), and appends
the proposal. Stopping kills what has not started; a job already running in
another process is not killable, and the code says so rather than implying
otherwise.

## Gaps as issues: three graphs, one board

A gap is not a property of prose. It is a property of a graph, and the same
detector runs on the three graphs people actually work in:

```
text      two clusters that never co-occur           nodus.find_gaps
code      modules that share vocabulary, no edge     ast + import graph
tickets   open issues, located in the modules        GitHub REST
```

They become one `issues.Issue`: title, why, evidence with locations, **the
queries that would close it**, a `confirm` sentence that says what would prove it
real, and a status (`open | solved | wontfix`) kept in `solve/issues.json`.

The board is the marimo notebook, because a table with selection, filters and a
detail pane is a solved UI problem and hand-rolling it in HTML was the wrong use
of the afternoon. `board.py` gives you: source dropdown per document / code path
/ repo, a filterable table, the evidence and numbers for the selected card,
state buttons, a **search** block (each query is a live DuckDuckGo link), and a
chat box wired to the local Qwen model *grounded on the card* — with the card
pasted into the fallback when the model is down, so the panel is useful either
way.

What each source is allowed to claim, and nothing more:

| source | filed as | confidence | why |
|---|---|---|---|
| text gap | gap, polarised | 1.0 | measured on this document; `confirm` asks for a typed relation across the divide |
| import cycle | defect | 1.0 | decidable from the import graph |
| detached module | defect | 0.9 | no local edges, no `__main__`, no top-level code |
| unused definition | candidate | 0.7 | decidable *inside the tree*; external callers are invisible |
| shared vocabulary, no edge | candidate | 0.35 | could be a missing abstraction or two modules using the word "value" |
| GitHub ticket | ticket | 1.0 | it is already a claim; the engine only locates it |

On this repo the board currently files: `compass.py` imported by nothing, six
definitions never mentioned again, no cycle, and two vocabulary overlaps. The
dead-definition check skips decorated functions — `@formula`, marimo cells and
Flask routes are live without their names reappearing, which was a false
positive until the test for it existed.

**The limit I will not paper over.** No graph can know an absent edge was
intended. That is why only cycles, orphans and unreferenced definitions are
called defects; everything inferred from shared words is a candidate with its
falsifier written down. Reading the tooling literature (see `SOURCES.md`) made
this sharper: Graphify builds a code graph but does not detect missing links,
Arcan/Import Linter check *declared* rules, and Clio compares co-change history —
which this repo does not do yet, though git history is right there.

`issues.merge` dedupes across sources, so a GitHub ticket that names the same
module as a code gap sits next to it rather than in a second tool.

## The sheet: the cell's language picks the widget

`sheet.py` is a notebook, not a chat and not a dashboard. A cell is source text
plus the view its language asks for:

| the cell says | the view | why |
|---|---|---|
| a paragraph | prose | no other signal |
| `![cat crossing the road](assets/cat.svg)` | image | names an image path |
| "predator and prey populations oscillate…" | **Lotka–Volterra plot**, drawn from the sentence | dynamics vocabulary |
| a sentence ending in `?` | question | a question is not a simulation — this ordering was a bug until the "game-theoretic vs predator-prey" cell rendered as a phase plot |
| `$…$` or `!gap(a,b)` | live formula | formula syntax |
| a sentence with because/therefore/requires | claim | states a relation, checked as one |

Two deciders, deliberately unequal. `cells.infer()` is deterministic, ~1 ms, and
prints its reason in the cell header (`plot — predator/prey vocabulary`).
`cells.choose_view()` asks the 0.5B model to pick from the same closed set. On
the five seed cells it is **1/5**: it agrees on the image, calls the duck prose a
plot, the predator-prey sentence a quote, the question a formula, and the human
seed a claim. So the model's choice is a toggle, the rules are the default, and
the header prints both when they disagree.

**Latent context.** Every cell is text for the graph. `cells.read()` returns the
links, gaps and per-cell terms; `Cell.latent` carries each cell's slice. That
slice goes into Qwen's prompt and is **not rendered in the cell**. A single
switch at the bottom reveals the whole read, because a system that hides its
context completely cannot be debugged.

**The chain is visible.** `run one round` calls `cells.step()`: nodus ranks a
gap, `localmodels.route` asks Needle (act/confirm/refuse, with confidence and
milliseconds), qwen picks a direction from the three questions and either drafts
a sentence or picks a real span, and nodus builds the cell. The log under the
sheet is that chain verbatim — `needle ask @ 0.04 in 1309 ms` — not a spinner.

The issues board is at the bottom of the sheet, computed from the same text, so
the loop and the tickets are never two different readings of the corpus.

## Five AI papers: what the loop actually did

`bridge.py` runs the question you posed: five abstracts + one human sentence →
gap → needle → qwen → a new cell → re-analyse. Corpus: Co-Scientist, Robin,
Kosmos, GraphRAG, The AI Scientist (abstracts in `papers/`).

Start: **1155 words · 716 concepts · 2 unbridged gaps · modularity 0.458.**

| mode | rounds | typed relation crossed | gaps after each round |
|---|---|---|---|
| draft (qwen writes the sentence) | 3 | **0/3** | 2 → 2 → 2 → 6 |
| quote (qwen picks a real span) | 2 | **0/2** | 2 → 3 → 4 |
| control (`<a> implies <b>`, no model) | 1 | **1/1** | 2 → 2 |

*Those numbers are for the original hand-picked five papers. On five random cs.AI papers (seed 2026, live Qwen) the result is the same direction: the constrained draft rejected all three sentences for lacking a relation verb, and quote mode wrote real sentences that crossed no typed relation (see `experiment.md`, round 2). The knowledge check counts a relation only when it crosses the gap and both sides are grounded, so the six-token control no longer passes.*

Three results, and only the third is comfortable:

1. **The chain runs end to end.** Every round produced a cell and a log with
   needle's confidence, qwen's direction, and the ontology check. Nothing in
   that is a claim about quality.
2. **The draft worker produces fluent vacuity.** Round 1: *"The two topics
   connect by demonstrating the versatility of a model in three distinct
   subfields of machine learning…"* — grammatical, on-topic, and empty. It
   paraphrases the abstracts' own phrases (`GraphRAG`, `test-time compute`) into
   sentences that assert nothing. The quote worker cannot close a gap by
   construction: the sentence it picks was already in the corpus.
3. **The control is the finding.** `automat implies model.` — six tokens, no
   model, no evidence — passes the typed-relation check. So the acceptance test
   is a *syntax* gate, not a knowledge gate, and a loop that stops on "no gaps"
   can be satisfied by a template. The gap count is also unstable in both
   directions: adding text re-partitions the graph, so it rose to 6 in the draft
   run while nothing crossed.

What would make it a real loop, in the order the papers suggest: rank hypotheses
(Co-Scientist's tournament), check each statement against the source it cites
(Kosmos's 79.4% statement accuracy is measured against exactly this), and run
the experiment (Robin). Nodus has none of the three, and says so.

## Determinism was broken, and is now tested

The README claimed `nodus.analyse()` was deterministic. It was not: three
processes on the same corpus returned **9, 8 and 7 clusters**. Two causes, both
hash-order:

- `build_graph` added nodes by iterating a `set`, and Louvain's RNG consumes
  them in insertion order;
- `resource_allocation` and `adamic_adar` summed over a `set`, so last-bit float
  differences reordered tied gaps.

Both now sort. Three separate processes return the same six gap ids and the same
scores, and the sample document's rankings are unchanged (0.346, 0.273, 0.142,
0.101). This matters beyond tidiness: a loop that compares a gap count before and
after cannot tell a real change from a re-seeded partition.

## The theory, sourced

`SOURCES.md` replaces the loose citations that were here. The corrections that
mattered: the citable method paper is Paranyushkin's **2019 WWW paper**, not a
blog post; the four-way discourse thresholds are Nodus's own, not published; and
Burt's *structural holes* is a theory of missing social ties — using the phrase
for lemma clusters is an analogy, and the code no longer implies otherwise.

## What one of those bridge cards actually says

The compass card is one absent pair and the numbers that ranked it:

```
bridge sentence ↔ reply
missing sentence → window · absent 0.58σ · RA 0.70 · tension 0.11
2 links · cross 0 · porosity 0.00
```

Read it left to right:

- **`sentence ↔ reply`** — the two *clusters* being compared. Their labels are their most frequent members, not a summary.
- **`missing sentence → window`** — the specific absent edge the evidence is about. One pair, named.
- **`absent 0.58σ`** — how much more often that pair is absent than the block-shuffle null expects (`z = (E[observed] − observed)/sd`).
- **`RA 0.70`** — weighted Resource Allocation for that pair: how much its two neighbourhoods suggest the edge should exist.
- **`tension 0.11`** — kNN profile cosine: do these two live in the same vocabulary? High tension means "same subject, different words"; low means "two strangers".
- **`cross 0`** — total edge weight *between the clusters*. Zero means nothing at all crosses this divide.
- **`porosity 0.00`** — that cross weight as a share of the thinner cluster's own internal weight. This is the one that stops bad suggestions.
- **`2 links`** — hops between the clusters' core terms in the current graph.

Two bugs this layout fixed. First, `z`, `RA` and `tension` used to be three independent maxima, so a card could quote three different missing pairs at once and read like evidence for a claim nobody had computed. There is now one chosen pair and its own three numbers.

Second, the previous card said `7 shared edges · absent 2.21σ` on a divide that was heavily connected. Both statements were true and the combination was nonsense: the 7 was cross-weight, the 2.21 belonged to a different, unnamed pair. A divide crossed by a fifth of the thinner side's weight is a **seam, not a hole**. Above `porosity 0.25` a gap is marked `already bridged`, its score is multiplied by `1/(1+3·porosity)`, and the compass moves it below the real holes. On the sample, `reply ~ source` (porosity 0.83, RA 1.48) drops from rank 3 to 5.

## Two layers, and the invariant that makes them a layer

This is the part that was missing. The same graph is read at two scales:

```
machine   fine clusters · every absent pair · every statement span     → agents
human     ≤5 regions · top moves · gist sentences                      → reading
```

A region is a **merge of fine clusters**, not a second clustering. `nodus.layers()` builds the fine layer first, then absorbs the smallest clusters into their best-connected neighbour until at most five regions remain — so `Layers.consistent()` can prove the relationship: every fine cluster lands in exactly one region, no node is lost, and anything named on the page resolves downward into the evidence behind it.

Both layers are printed. The overview cell lists each region with its size and how many machine clusters it contains; every gap card names the two machine clusters and the region they sit in. The agent packet carries the same mapping under `structure`, so a worker's answer can say which readable part of the page it belongs to and be checked at the resolution the numbers were computed at.

What this buys, concretely:

- the map can be read at a glance (colour = region) while the compass still argues about exact clusters;
- a 200-document corpus can have 40 clusters without the page becoming a hairball;
- **a finer clusterer now has somewhere to plug in.** Louvain sits at both scales today; torque clustering would replace the fine layer and leave the human layer's construction untouched. That is the seam, not a rewrite.

## A corpus decides the page, not a template

Drop documents into the file input and `corpus.organize()` builds one graph, splits it into layers, and works out which documents cover which regions. `corpus.plan()` then emits cells with a priority and a stated reason:

| cell | when it earns the space |
|---|---|
| `overview` | always, first — counts, structure label, region legend |
| `gap` | per top gap; high when nothing spans the divide, halved when something does |
| `coverage` | documents against regions; leads when the pile is dispersed or unorganized |
| `witness` | regions covered by exactly one document — losing it would erase a region |
| `orphan` | documents the graph could not represent (most vocabulary below the frequency floor) |
| `ledger` | your writing; last of the analysis, because it is the slowest thing to read |
| `decision` | the record, once there is a gap to file against |

The order is derived, so it moves: a dispersed pile leads with coverage, a two-region pile with no bridge leads with the hole, a pile where one document is the only witness leads with that document. Verified on a synthetic 207-document corpus (200 proof-like papers, 3 deliberate bridges, 4 off-topic) — 0.9s to organize, 179 concepts, 10 clusters, 5 regions; and on the single-document sample, where the same rules put the ledger between the gaps and coverage.

Scale guards, all documented in code: betweenness is sampled above 600 nodes (it is O(nm) and only ever gets square-rooted), only the 14 most influential clusters are paired, only the 18 strongest nodes per side are searched for the absent link, and the minimap draws the top 240 nodes instead of all of them.

## The page is a notebook, not a dashboard

The first version put a sticky strip of four gap cards above the document, then the prose, then an editor at the bottom and two forms. That is a dashboard, and it is why it read as confusing: analysis separated from the text it was about, the input below its own output, and actions in a global toolbar. Wolfram and SolveIt both solve this, and the page now follows both:

```
In[1]   the editor, where you type              ── above its own output
Out[1]  the document, with margin notes
In[2]   only when you pick a gap: what's missing + the forms
Out[2]  what an agent would receive for that gap
        the shape behind the page ▸ (folded)
```

- **Input above output**, numbered in the gutter, bracket on the left. The editor is no longer a panel bolted to the bottom.
- **No global toolbar.** A gap is a margin note beside the message that talks about both its sides — placed by counting term hits, not by a layout model, and it prints the hit count so a wrong placement is visible rather than mysterious. The note carries its own `work on this` button; the action lives where the problem is.
- **Plain language first, numbers behind `why`.** A note says *nothing links window to citation* and *the absent link is window → citation*, then `0 edges cross · 2 links apart`. σ, RA, tension and porosity are one disclosure away, for the reader who wants to argue with the ranking.
- **Everything else is folded.** Overview, coverage, witnesses, orphans and the record live under *the shape behind the page*, closed by default.

Folding and selecting are rendering only. The page is generated from `corpus` + `dialog.ipynb`, so a closed cell still reaches `Dialog.context()` and a margin note cannot change what an agent receives. `orchestrator.queue()` remains the proof: three packets built from the ledger, each with per-message modes (`full | gist | pointer`), a withheld list with ids, and a span-required schema.

The editor backend is the claim worth testing: **a closed cell changes nothing.** The page is generated from `corpus` + `dialog.ipynb`, never from its own HTML, so folding a cell cannot alter what an agent receives. `orchestrator.queue()` is the proof — three packets, ~2.3 KB each, built from the ledger and the graph, listing for each task the objective, the numbers, the allowed context (`full | gist | pointer` per message), what is withheld and retrievable, and the claim schema with mandatory span ids.

That is the split you asked for: a human sees regions, a gist and four moves; a supervisor gets one objective, bounded context and a schema it cannot lie its way out of.

## The map, with a way out

Four controls, one integer (`0` closed, `1` corner, `2` full):

| state | what is on screen | controls |
|---|---|---|
| 0 | nothing but a `map` chip in the corner | `map` → 1 |
| 1 | 172×172 minimap, no labels | `expand` → 2, `× close` → 0 |
| 2 | 980×620 labelled graph | `minimise` → 1, `× close` → 0 |

The old overlay was `position: fixed` at z-index 80 covering the corner toggle at z-index 40 — a one-way door with no exit control. Every state now renders the control that leaves it. Structural check: exported in all three states, the button census is 7 / 8 / 8 — `map` replaced by exactly `expand + close` and then by `minimise + close`, with no chip underneath the overlay.

## kNN, torque clustering, CAL AutoHead — the honest table

| term | status |
|---|---|
| **kNN** | implemented in a stated space: each concept is an L2-normalised vector of its own edge weights (`nodus.profiles`); `knn()` returns the strongest *non-edges* |
| **kFN** | implemented as the same search at the far end — a diversity check, not an outlier score |
| **temporal geometry** | implemented as **positional** geometry: a single document's only time axis is sequence index, so each concept gets a position histogram and a gap's `offset` is `1 − cosine` between the two clusters' pooled histograms |
| **torque clustering** | a **real published algorithm** by **Jie Yang and Chin-Teng Lin** ([arXiv 2004.13160](https://arxiv.org/abs/2004.13160), [code](https://github.com/JieYangBruce/TorqueClustering)) — not Aragon's, and **not ported**. The layer split above is the prerequisite: it needs a fine layer to replace |
| **CAL AutoHead** | no public spec, architecture or code. Nothing here claims to implement it |

I would not ship invented maths under someone's name, so the three names I could not source are labelled as such rather than approximated.

## The gap score

```
score = sqrt(influence_a · influence_b) · (1 + z) · (0.5 + tension)
        / ((1 + log(1 + cross_weight)) · (1 + 3·porosity))
```

- `influence` — summed betweenness per cluster. It answers "does anyone care", not "is something missing".
- `z` — expected-but-absent co-occurrence from a **block** shuffle (word order inside ~25-token blocks survives; a full shuffle destroys syntax and makes every topical pair look surprising).
- `RA` — Zhu & Xia's weighted Resource Allocation, `Σ (w_uz + w_zv)/s_z` over shared neighbours. On lexical co-occurrence it scored **0.872** top-100 precision where Adamic-Adar got 0.571 and common neighbours 0.447; AA is computed alongside so the choice is visible.
- `tension` — kNN profile cosine. `(0.5 + t)` rather than `(1 + t)`, because a pair with no semantic overlap is two strangers, not a hole.
- `porosity` — the anti-seam term.

**Limits.** No paper benchmarks a "better than InfraNodus" score; this is an augmentation. Peng et al.'s predictive models explained ~16% of variance, so no single number here is ground truth. Burt's constraint is a brokerage diagnostic, not a missing-link score, and stayed out.

## The theory I had left out

Three pieces of the original method were missing, and the page is worse without them.

**The four-way discourse read.** A text network has two axes: how concentrated attention is, and whether the clusters are actually joined. InfraNodus names the quadrants; the thresholds were never stated, so here they are:

```
concentration = share of all edge weight held by the largest cluster
cohesion      = modularity
diversity     = normalised entropy of attention across clusters
polarity      = disconnection between the two heaviest clusters

concentrated + cohesive -> focused       one theme, well argued
concentrated + loose    -> biased        one theme, everything else unattached
spread       + cohesive -> diversified   many themes, each coherent
spread       + loose    -> dispersed     many themes, none joined
```

On the sample: **diversified, diversity 0.89, attention 0.40, cohesion 0.47, polarity 0.90.** Those numbers are in the header now, because "diversified" alone is a horoscope.

**The statement layer.** A concept graph says two clusters never meet; it cannot say which sentence comes closest to joining them. `bridge_candidates()` scores every sentence by cosine to both cluster centroids in the same space kNN uses, skips any sentence that already touches both sides (if it existed the clusters would have an edge), and returns the nearest one. That sentence is printed in the margin note and in the gap cell. Two milliseconds for three gaps on a 556-word document, so it survives a keystroke.

**The question triad.** Nodus generates three prompts per gap, not one: *develop* (what does X imply that the document has not said), *connect* (what would connect X to Y), *explore* (what is missing between X and Y). One "how does A relate to B" reads as homework; the three together give a writer a way in whichever direction they think.

Still absent from the theory, and named rather than faked: **temporal evolution** (the same graph at two points, for "what changed"), **embedding-based clustering** (synonyms are still invisible to a lemma graph), **entity extraction**, and InfraNodus's original gap formula `influence/(1+cross)`, which is kept only as `cross_weight` in the card because it measures existing paths, not missing ones.

## Ontology: the layer co-occurrence cannot see

Three levels were already distinct, and one was missing:

```
concept   a lemma                                  nodus.concepts
paper     a cluster of concepts                    nodus.clusters
domain    a merge of topics                       nodus.layers (human)
ontology  a *typed edge between two concepts*       ontology.py   <- new
```

`ontology.relations()` reads a closed set of cues — causes/implies, is-a, part-of, contradicts, requires, supports — and keeps only relations whose two ends are concepts the graph already has. No parser, no model; a census of what the document actually asserts.

The result on the sample is a useful negative: **1 typed relation in 556 words** (`citation is-a claim`), and **0 crossing the top gap**. That is a much stronger statement than "these words never appear together": nothing in the text *says* how window and citation connect. The gap card now carries `typed links: none` and, when relations exist, lists them.

This also gives the loop something to check against, which is the point below.

## The loop: why gap count is a bad objective

`controller.run()` implements what you described — a policy decides act / confirm / refuse, a worker proposes text, the graph is re-analysed, and the loop repeats until a stopping rule fires.

Measured on the sample, each bridging sentence removes about one gap:

```
step 0   4 unbridged gaps     (top score 0.346)
step 1   3                    (top score 0.122)
step 2   0
```

That convergence is real, and it is a warning. Any sentence containing both sides' words creates the co-occurrence edge, so the metric is satisfiable by keyword stuffing. Acceptance therefore does **not** test the graph, it tests the ontology: the new text must state a typed relation whose ends sit on opposite sides. Running both workers:

```
keyword stuffing     rejected: no typed relation crosses
states a relation    accepted: dependency: sentence -> reply   (gaps 4 -> 2 -> 3)
```

Note the accepted run went 4 → 2 → 3: closing one gap opened another elsewhere, which is the normal behaviour of this loop, not a bug. Stopping rules, in order: no gaps · policy says confirm/refuse · worker empty · rejected · stable (same gaps, modularity within ε) · step budget. `deterministic_policy` stops when the top gap falls under 0.12, because below that the interruption costs more than the hole.

**Needle as the always-on controller does not hold up.** I tested the three-way design as described — options as tools, Act/Confirm/Refuse, confidence threshold, exactly the contract the docs describe. On five cards it chose `act` for an off-topic request and `act` for a claim with no source, and suppressed the calls where acting was correct; confidence stayed between 0.01 and 0.17 throughout. The wrapper `needle_policy(threshold=0.5)` therefore falls back to asking the human on anything it is unsure about, and the deterministic policy remains the default. The architecture is right; that model is not the thing to put in that seat yet.

`eval_route.py` settles whether that is *scale* or something else: 20 labeled cards (8 draft / 6 stop / 6 ask), facts stated on the card so lookup should be perfect, three routers on identical input. Needle is scored twice, because the engine suppresses every call below confidence 0.1 — *refused* and *wrong* are different failures and must not be summed: **act** is what a threshold caller sees, **selection** also reads the held-back call:

```
                       act       selection    notes
rules                  100%      100%    floor by construction - facts on card
qwen (0.5B)            75%       75%     stop 6/6 · ask 6/6 · draft 3/8
needle, original card  0%        55%     19/20 held back · draft 5/8, ask 6/6,
                                         stop never chosen
needle, intended card  0%        50%     enum-style rendering (functions named
                                         up front, as Cactus documents) did NOT
                                         help; confidence fell, max 0.196 → 0.045
needle, +forced        50%       50%     floor removed: act = selection, still
                                         below Qwen, stop still never chosen
confidence             min 0.002 · mean 0.03 · max 0.196 · at ≥ 0.5: 0 cards,
                       every run, every format
```

The first published pass printed needle at 30%; rescoring honestly — an empty answer is `none`, not `ask` — it dispatched **one call in twenty** (act 0%) and the six "correct" asks were abstentions. Held-back calls are real choices though, which is where selection 55% comes from: the model's picks are mediocre-but-informative, its actions are absent.

`eval_native.py` then moves the question to needle's **own** seat — `cells.card()` task cards built from real unbridged gaps, every field in words — and the result splits the verdict in two:

```
production card          selection 0%    grounds a='Bridge', b='any two areas'
                                         - the seed's generic words - and picks
                                         ask on every gap, floor or no floor
same card, direction     selection 100%  6/6 draft: copy-don't-compose works
names the gap                            exactly as documented once the
                                         imperative names the arguments
either way               act 0%          confidence 0.001–0.022, nowhere near
                                         the 0.1 floor
```

The native-seat failure was therefore **our card**: `cells.card()` puts the seed cell's text in the direction slot, and a seed that says "bridge anything" hands a copy-not-compose model nothing to copy. The cheap fix is now applied — `cells.card()` names the gap in the direction slot (e.g. "bridge Bridge to any two areas in one sentence"), and `decide()` reads both dispatched and held-back calls, reporting `selection` alongside `act`. With both changes, needle routes on its own seat exactly as its docs promise: selection 100% (6/6 draft) on cards that name the gap. What still does not move: **the act gate never opens** — confidence never leaves 0.001–0.196 across six live runs, so no threshold on this model can fire at any seat or format.

Three separate failures hide behind the one symptom. **Seat mismatch is the biggest**: needle is a grounding model — it abstains unless it can retrieve every argument literally from the card, so on routing it mostly emits nothing, and the fallback (`ask`) is also its most-predicted class. **Calibration is independent of size**: its confidence never leaves 0.003–0.2 whether it is right or wrong, so no threshold can ever gate on it. **Scale is real but third**: Qwen-0.5B — one tenth the bytes — routes the same cards at 75%, losing only on `draft` cards where it fails to read "unbridged" as work to do. A bigger needle would likely route better; it would still need calibration before its confidence meant anything, and it would still be the wrong seat for a model that refuses to decide without evidence.

This matches what the community reports rather than contradicting it: the router evaluation in `cactus-compute/needle#61` ended *"Not adopting Needle for this router in its current form"*; a 360-example fine-tune study saw negative-case detection collapse 24/24 → 0/24 on its pinned version; the Show HN thread's one labeling attempt was *"very bad; MNLI was better"*. The act/ask/refuse bands people borrow for decision-shaped tasks are Cactus's documented policy (act ≥ 0.7, ask 0.1–0.7, engine suppresses < 0.1) — vendor guidance, not a demonstrated production pattern. Nothing found shows Needle 3 running a Jev-style approval gate in production; Jev (TypeSafe) is a different product class anyway — closed weights, cloud API, typed decisions with calibrated probabilities, 63.7% in its one independent test (LangWatch) — inside the same 60–75% band as Qwen here, so bytes alone settle neither product's seat.

## The truth gate: quote the evidence

A crossing proves the sentence *states* a relation across the divide. `truth.py` asks the next question: can the claim *point*? — the Kosmos-style requirement that a drafted claim cite spans a human can actually read.

```
spans     double-quoted text of 12+ chars, plus blockquote lines (mode="quote"
          cells ARE corpus sentences, so the blockquote is a citation)
find      the span's word sequence must occur in the corpus after
          normalisation - punctuation and case are presentation, word order
          is content. Rewording fails by construction: a citation the corpus
          does not contain is a hallucinated citation. An elided quote
          ("A ... B") may cut only where every fragment occurs.
gate      at least one citation, every citation findable; the reason string
          is what the log line and the control event carry
wiring    cells.step computes the verdict on every draft - `gate pass|blocked
          - reason` in the round log, full verdict in cell.meta['truth'] - and
          blocks only when step(..., truth_gate=True). Opt-in keeps the
          harness probe and older runs comparable. A block emits a `control`
          event like every other hidden decision. Paper cells are the
          evidence when the sheet has them.
```

16 tests in `test_truth.py`: the units, plus the wiring — default logs without blocking, an uncited draft stops with no cell, a draft citing the corpus writes, quote mode passes. What it does **not** do is verify truth: only that the words exist in the papers. And no nudge tells Qwen to quote yet, so with the gate on an uncited draft is a stop, not a retry.

## The harness is editable, and nodus is the gate

Google's Harness² ([arXiv:2610.14224](https://arxiv.org/abs/2610.14224)) freezes the model and moves improvement into the harness: propose an edit, probe it, keep it only if it works. `harness.py` is that loop here, with one addition — **the probe is Infranodus, not a benchmark score**:

```
propose   qwen writes one JSON edit against a closed set of three fields
          (draft_system · draft_tries · draft_hint); deterministic rules answer
          when the model is down or returns invalid JSON — recorded, not hidden
probe     the candidate runs cells.step on the fixed papers corpus;
          the live harness is restored no matter what the probe does
gate      keep the edit only if crossings rise, or if crossings hold while
          valid drafts rise and failures do not; otherwise REJECT, with why
record    every attempt, kept or rejected, lands in solve/harness_trace.json
```

The editable surface is deliberately three fields. A harness the model can rewrite wholesale has no gate worth the name — the gate only means something because the set of things it may touch is small and closed.

First live cycle (Qwen up, seed + five random papers):

```
before  3 drafts rejected, 0 valid, 0 gaps closed (stopped: qwen produced nothing)
propose draft_hint by qwen: Start with a clear, concise sentence linking the two research areas.
probe   3 drafts rejected, 0 valid, 0 gaps closed (stopped: qwen produced nothing)
gate    REJECT - no improvement (crossed 0, drafts 0)
```

Qwen proposed a valid edit; the probe showed it changed nothing; the harness stayed exactly as it was. That is the intended outcome: proposals cannot buy their way in with a nicer-sounding prompt, and the rejected attempt is still on the record. The sheet has the button — *"qwen edits the harness · nodus gates it"* — and the verdict prints into the round log.

## Our own DeltaDB: every operation, stable identity, state as a fold

Zed's DeltaDB ([zed.dev/blog/introducing-deltadb](https://zed.dev/blog/introducing-deltadb)) is closed, the same-named GitHub project is an unrelated JS document database, and the event-sourcing frameworks are heavier than the tool. So `delta.py` is the pattern at this repo's size, stdlib only:

```
append-only    solve/delta.jsonl, one line per operation, never rewritten
stable id      ULID per event - time-sortable, monotonic within a millisecond
dag lineage    parents: [hash] instead of a single prev - two agents citing
               the same observation create a fork (legal data, not corruption);
               base= pins the state an event is about; tips() lists open ends
               legacy chain-era lines ('prev') still verify and extend
fold           state is a fold; state_at(seq) reconstructs any past state
               file order is topological: a parent always precedes its child
```

**Our own notary.** `checkpoint()` writes a receipt inside the log: the hash of
every line before it plus the tips. `verify()` alone accepts a *re-linked* rewrite
(an attacker who fixes every parent after editing history); `verify_checkpoints()`
recomputes what each checkpoint covers and refuses it. Honest limit: this runs
on the same machine as the log, so it raises the bar (corruption, partial edits,
re-linking, casual tampering) without removing it — the checkpoint's `log_sha`
is exportable, and an *external* copy of it (git, another machine, a ledger like
HCS) is what makes the notary independent.

**Latent control.** `cells.step(..., sink=...)` emits `control` events — needle's
route and nodus's verdict — each citing the gap it observed. The sheet wires the
sink; the reader never sees these; the log keeps every hidden decision walkable
to its evidence.

What it records, and what that buys:

| event kind | written by | replay gives you |
|---|---|---|
| `cell_add` / `cell_edit` | sheet buttons, run-one-round (actor: human/qwen) | every cell's text **and the text each edit overwrote** (`previous`) — `cells.edit()` no longer destroys history |
| `sheet_state` | reset / load-papers | the full sheet as it stood |
| `control` | `cells.step` via the sheet's sink (actor: needle/rules, nodus) | which gap each hidden decision saw and what it ruled |
| `checkpoint` | `checkpoint()` | log coverage receipt — catches re-linked rewrites |
| `harness_edit` | `edit_once`, every attempt (actor = who proposed) | `fold_harness()` = the harness state at any point, kept edits only |
| `experiment` | `record_context` (run_loop) | result → corpus file hashes + harness state + model availability — provenance, the "message and the edit side by side" half |

`delta.state_at(delta.cell_reducer, {}, seq=N)` is the undo primitive; `delta.verify()` + `verify_checkpoints()` are the tamper checks. 15 delta tests cover roundtrip, monotonic ids, tamper detection at the right line, forks, unknown-base rejection, legacy chain files, the re-link attack, both folds, past-state reconstruction, control events, and the context snapshot — 54 total.

## The budget: the gaps decide how many agents run

`plan.py` ends the endless-loop problem by construction. The open gaps *are* the budget:

```
A = min(open gaps, 3)            one lane per top gap, hard-capped
attempts = min(2 per gap, 9)     effort scales with the work, not with mood
G = ceil(attempts / A)           generations to spend it
patience = 1                     one silent generation and the run stops
```

Termination is decided **before** the model is asked: batches ≤ A × G ≤ 9 no matter what Qwen returns, and cells may only stop it earlier (no gaps left, patience spent, refusal). No plan runs unapproved — needle sees the whole budget as a card (lanes, scores, caps, stop rules) and may approve, adjust generations (clamped 1..4, so it can never *raise* the cap), or refuse; needle being down falls back to rules approving, recorded `by=rules`. The approval lands as a `control` event like every other hidden decision.

Live on the five-paper sheet: `3 subagents × 2 generations · cap 6` → needle approved in 3.8 s → generation 1 ran its three assigned gaps (`target=` per lane) → no crossing, gaps 3 → 5 → **`patience spent`, 3 batches of 6 used**. The same sheet under the old loop would have kept going.

## Local models: installed, measured, and mostly not trusted

Both run on this device, no network, no API key (`.models/`, 580 MB, gitignored) — and the no-network claim is measured now, not assumed: strace shows `needle.bin` opens **zero network sockets** across a full inference, and the binary embeds no external URL (the telemetry the ValueStreamAI guide warns about in the stock Needle build is not in this one):

```
needle3.cact          34 MB   Cactus Needle 3, CQ2, 79 MB peak RSS
qwen2.5-0.5b-q4_k_m  469 MB   Qwen2.5-0.5B-Instruct via llama.cpp b11827
```

`bench.py` reproduces every number below; `localmodels.py` is the client.

| job | model | result |
|---|---|---|
| route a command to one of three actions | Needle | **2/4 exact.** Refuses more often than it errs (confidence collapses to ~0.01), which is the safe failure — but it is not reliable enough to press a button unattended |
| copy arguments out of a card | Needle | works when every argument is literally in the prompt; cannot compose an objective, only copy one |
| extract a verbatim gist with spans | Needle | **fails.** Empty and refused, or (forced) a whole passage with one clause silently deleted — the worst possible failure for citations |
| choose among four labels | Qwen 0.5B | **works** when the answer set is a JSON-schema enum; 0.6 s |
| free-form quote | Qwen 0.5B | inconsistent: verbatim on one run, paraphrased on another |
| write a filter expression | Qwen 0.5B | wrong both runs (`text.split("citation")`) |
| tool call in JSON | Qwen 0.5B | wrong tool, and put the utterance where the cell id belongs |

The useful conclusion is not "the small models are bad". It is that **grounding is a safety property and judgement is not**: Needle knows when it has not found an argument and says no, which makes it a defensible confirm/refuse gate in front of a real action. Qwen will produce a confident, well-formed, wrong answer, which makes it safe only behind a closed-set grammar.

Latency matters for the "alive" question: a needle CLI decision costs **1.5–2.3 s** because each call reloads the 34 MB model, while the deterministic gap engine costs **18 ms**. Live gaps, live regions and a click-to-open inspector therefore cannot be built on the model path — and do not need to be.

## What is not built, and what is verified

**Not built:** no model writes into a cell — both local models are installed and measured, but neither is allowed to produce cited text, because the routing one is not accurate enough to act unattended and the small one cannot quote reliably (the board's chat is read-only, and its quotes are for a human to check); no sub-agent dispatch — `queue()` is a queue, and whoever runs the workers decides whether to take the top item, all of them, or none; no co-change/Clio analysis of git history; no Leiden or torque clustering; no CAL AutoHead.

**Verified:** `marimo export html` executes every cell of `app.py`, `board.py` and `sheet.py` (exit 0); the sheet's payload contains all five seed cells, the plot's two polylines, the question cell and the issues strip; the board's payload contains 15 cards (4 text, 11 code) with evidence and labels; the plan order, region legend, gap evidence tables, citation chips, queue and packet are present in the exported payload; `corpus.organize` on 207 synthetic documents runs in 0.9s and produces a coherent plan; `Layers.consistent()` passes on the sample; `python -m unittest test_issues` passes 13 tests covering the code parser (cycle, orphan, decorated-definition skip), the GitHub parser with an injected fetcher (PR filtering, closed→solved, error surfacing), pagination dedupe, `locate`, and the JSON round trip. `bridge.py` reproduces the five-paper experiment above; `cells.choose_view()` was measured at 1/5 agreement; three separate processes now return identical gap ids.

**Not verified:** the GitHub adapter has never made a real request — **this sandbox has no outbound network** (`curl https://api.github.com` times out), so it is written to the documented API and tested against a fake transport, nothing more. Also unverified: clicks and layout in a browser (none installable here). The sheet's `run one round` was exercised through `cells.step()` headlessly, not by clicking; the marimo button wiring is the same pattern as the board's, which is also only structurally checked.
