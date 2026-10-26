# Five AI papers, one human cell, and what the loop actually did

Corpus: five arXiv abstracts fetched 2026-10-22, plus one human sentence.

```
ai-coscientist.md       185 words
ai-scientist.md         234 words
graphrag.md             232 words
kosmos.md               239 words
robin.md                243 words
```

Human cell: *None of these systems convinces me that a new claim is true; I want to see what each one treats as evidence.*

Start: **1155 words · 716 concepts · 2 unbridged gaps · modularity 0.458**

| # | mode | gap | direction | cell | typed relation | gaps after | ms |
|---|---|---|---|---|---|---|---|
| 1 | draft | automat~model | What does automat imply that these paper | The two topics connect by demonstrating the versatility of a model in  | no | 2 | 3825 |
| 2 | draft | research~model | What does research imply that these pape | Conditioned on their research objectives and prior scientific evidence | no | 2 | 5699 |
| 3 | draft | model~therapeutic | What does model imply that these papers  | To combine the strengths of these contrasting methods, we propose Grap | no | 6 | 6686 |
| 1 | quote | automat~model | What does automat imply that these paper | > Automated evaluations show continued benefits of test-time compute s | no | 3 | 3878 |
| 2 | quote | automat~kosmo | What does automat imply that these paper | > The system's design involves agents continuously generating, critiqu | no | 4 | 3735 |

## The cells the loop created

**[qwen-draft] automat~model** — 2 gaps after

> The two topics connect by demonstrating the versatility of a model in three distinct subfields of machine learning, supporting the model's ability to adapt and improve over time.

```
nodus   gap automat~model score 0.030 (2 unbridged)
needle  ask @ 0.02 in 1528 ms - 'automat to model, score 0.03' -> a 'automat', b '0.03'; 'score 0.03' -> a 'score', b '0.0
policy  no human present: proceed with the top gap
qwen    direction: What does automat imply that these papers have not said yet? (782 ms)
qwen    sentence 778 ms - The two topics connect by demonstrating the versatility of a model in three distinct subfi
check   no typed relation crosses - []
```

**[qwen-draft] research~model** — 2 gaps after

> Conditioned on their research objectives and prior scientific evidence, it formulates demonstrably novel research hypotheses for experimental verification.

```
nodus   gap research~model score 0.022 (2 unbridged)
needle  ask @ 0.05 in 1473 ms - 'Cell sheet. Human direction: None of these systems convinces me that a new claim is true;
policy  no human present: proceed with the top gap
qwen    direction: What does research imply that these papers have not said yet? (1302 ms)
qwen    sentence 1503 ms - Conditioned on their research objectives and prior scientific evidence, it formulates demo
check   no typed relation crosses - []
```

**[qwen-draft] model~therapeutic** — 6 gaps after

> To combine the strengths of these contrasting methods, we propose GraphRAG, a graph-based approach to question answering over private text corpora that scales with both the generality of user questions and the quantity of data.

```
nodus   gap model~therapeutic score 0.026 (2 unbridged)
needle  ask @ 0.01 in 1515 ms - 'model to therapeutic score 0.03' -> a 'model to therapeutic', b '0.03'; 'score 0.03' -> a
policy  no human present: proceed with the top gap
qwen    direction: What does model imply that these papers have not said yet? (1210 ms)
qwen    sentence 2163 ms - To combine the strengths of these contrasting methods, we propose GraphRAG, a graph-based 
check   no typed relation crosses - []
```

**[qwen-pick] automat~model** — 3 gaps after

> > Automated evaluations show continued benefits of test-time compute scaling, improving hypothesis quality over time.
> 
> Direction: What does automat imply that these papers have not said yet?

```
nodus   gap automat~model score 0.030 (2 unbridged)
needle  ask @ 0.02 in 1495 ms - 'automat to model, score 0.03' -> a 'automat', b '0.03'; 'score 0.03' -> a 'score', b '0.0
policy  no human present: proceed with the top gap
qwen    direction: What does automat imply that these papers have not said yet? (1026 ms)
qwen    span 3 of 3 (1106 ms)
check   no typed relation crosses - []
```

**[qwen-pick] automat~kosmo** — 4 gaps after

> > The system's design involves agents continuously generating, critiquing and refining hypotheses accelerated by scaling test-time compute.
> 
> Direction: What does automat imply that these papers have not said yet?

```
nodus   gap automat~kosmo score 0.040 (3 unbridged)
needle  ask @ 0.00 in 1492 ms - 'automat to kosmo' -> a 'automat'; 'score 0.04' -> b '0.04'; 'draft one sentence into a ne
policy  no human present: proceed with the top gap
qwen    direction: What does automat imply that these papers have not said yet? (929 ms)
qwen    span 3 of 3 (1056 ms)
check   no typed relation crosses - []
```


## The control: a worker with no model at all

- `automat implies model.` — typed relation: **yes, causal**, gaps 2 → 2

## What this shows

1. The chain runs end to end: nodus ranks a gap, needle routes it (and usually asks, because its confidence is near zero), qwen picks a direction from a closed set, and nodus builds the cell. Nothing in that sentence is a claim about quality.
2. The draft worker produces grammatical vacuity. The quote worker cannot close a gap by construction: the sentence it picks was already in the corpus, so the knowledge was not missing, only its emphasis was.
3. The control is the important result. A sentence of the form `<a> implies <b>` built from the gap's own missing pair passes the ontology check with no model at all, and moves the gap count in the wrong direction (3 to 3 here, 3 to 4 on an earlier run). Gap count is therefore both gameable and unstable: adding text re-partitions the graph, so a loop that stops on 'no gaps' can be satisfied by a template and can also fail to stop while improving.
4. What would make it real: a judge that checks the new sentence against the papers it cites, and a claim that survives it. Neither 0.5B model can be that judge; 13 tests and 18 ms of graph arithmetic are not a substitute for one.

## Round 2 — five random cs.AI papers (live Qwen, seed 2026)

Corpus: five papers drawn by `draw_papers.py 2026` from the 100 newest cs.AI
submissions (2610.31553, 2610.31372, 2610.31202, 2610.31198, 2610.31097) plus the
human seed. Start: 980 words, 127 concepts, 7 clusters, modularity 0.489, 3 open gaps.
Qwen: `qwen05b-q4km.gguf` served by `llama_cpp.server` on 127.0.0.1:8090.

| mode | round | gap | drafts / span | typed relation crossed | gaps after |
|---|---|---|---|---|---|
| draft | 1 | across~record (0.074) | 3 of 3 rejected: no relation verb | — (stopped, no cell) | 3 |
| quote | 1 | across~record (0.074) | span 1 of 3 | **no** | 3 |
| quote | 2 | predict~record (0.121) | span 1 of 3 | **no** | 6 |

Reading: the constrained draft rejected all three Qwen sentences, because they
contained no relation verb (they copied paper text). Quote mode wrote real corpus
sentences; none crossed a typed relation, so no gap was closed. This matches the
earlier result: the loop, as built, does not close gaps on this sample.
