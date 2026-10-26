# Sources — what Nodus borrows, and what it only borrows the word for

Written after checking each claim against a primary page rather than a summary.
Three labels are used throughout, and they are not decoration:

- **peer-reviewed** — the claim comes from a paper with a DOI and referees
- **grey** — Nodus Labs' own writing, product documentation, or a repo README
- **analogy** — the name is borrowed; the construct is not the published one

## The text graph

| work | status | what it gives Nodus |
|---|---|---|
| Paranyushkin, D. (2019). *InfraNodus: Generating Insight Using Text Network Analysis.* WWW '19, 3584–3589. [doi:10.1145/3308558.3314123](https://doi.org/10.1145/3308558.3314123) | **peer-reviewed** | the method: lemmas as nodes, co-occurrence as edges, community structure for topics, and gaps between communities as the thing worth generating insight about. This is the citation for the whole approach — use it, not the blog posts |
| Paranyushkin, D. (2011). *Identifying the Pathways for Meaning Circulation Using Text Network Analysis.* Nodus Labs. [noduslabs.com](https://noduslabs.com/research/pathways-meaning-circulation-text-network-analysis/) | **grey** | the earlier argument that meaning moves along paths in a graph; background for `distance` / hop counts, not a measured claim |
| InfraNodus, *Text Network Analysis: methodology*. [docs](https://infranodus.com/docs/text-network-analysis) | **grey** (product docs) | the implementation details the paper does not pin down: sliding window, betweenness, cluster pairing |
| InfraNodus, *Cognitive Diversity*. [page](https://infranodus.com/about/cognitive-diversity) | **grey** (product docs) | the four-way read — biased / focused / diversified / dispersed. Nodus names the thresholds (`nodus.discourse`); no published paper states them |

**Correction to the earlier README.** There is no paranyushkin paper titled
"Generative Text Network Analysis", and "Text Network Analysis: Theory and
Practice" is a Towards Data Science article by Petr Koráb, not a Nodus Labs
publication. Both were removed rather than cited loosely.

## The new line (2024–2026): agents that generate hypotheses

The older literature says what a gap *is*. These say what to do after you find
one, and they are the systems this loop is measured against.

| work | status | loop, in one line | what Nodus takes, and what it does not |
|---|---|---|---|
| Gottweis, J. et al. (2025/2026). *Accelerating scientific discovery with Co-Scientist.* [arXiv:2502.18864](https://arxiv.org/abs/2502.18864), Nature (2026) | **preprint + peer-reviewed** | agents generate, critique and refine hypotheses; a **tournament evolution** ranks them; test-time compute improves quality; then in-vitro validation | the tournament is the missing judge here. Nodus has no Elo, no debate, no ranking beyond a graph score. Its automated evaluation is a weak proxy, which is the point of the next row |
| Ghareeb, A. E. et al. (2025/2026). *Robin: A multi-agent system for automating scientific discovery.* [arXiv:2505.13400](https://arxiv.org/abs/2505.13400), Nature (2026) | **preprint + peer-reviewed** | literature search agents + data analysis agents propose hypotheses, experiments, then interpret results **lab-in-the-loop** | the loop shape (hypothesis → experiment → updated hypothesis) is what `controller.py` implements; Nodus has no lab, so its acceptance test is textual, not experimental |
| Mitchener, L. et al. (2025). *Kosmos: An AI Scientist for Autonomous Discovery.* [arXiv:2511.02824](https://arxiv.org/abs/2511.02824) | **preprint** | a **structured world model** shared by a data agent and a literature agent lets 200 rollouts stay coherent; every statement cited to code or a paper; independent scientists rated **79.4%** of statements accurate | the world model is the closest published analogue of the shared graph here, and the citation rule is the one Nodus should copy. `Cell.latent` is a much smaller version of the same idea |
| Edge, D. et al. (2024). *From Local to Global: A Graph RAG Approach to Query-Focused Summarization.* [arXiv:2404.16130](https://arxiv.org/abs/2404.16130) | **preprint** | entity graph + pre-generated **community summaries** answer global questions over a corpus | GraphRAG answers the questions you already have; the gap engine looks for the questions nobody asked. The two share the community layer and differ in what they do with it |
| Lu, C. et al. (2024). *The AI Scientist.* [arXiv:2408.06292](https://arxiv.org/abs/2408.06292) | **preprint** | idea → code → experiment → paper → **automated review**, under $15 per paper | the automated reviewer is the evaluation Nodus lacks; an ontology check is not a reviewer, and `experiment.md` says so |

**What these change about this repo.** They move the question from "is there a
gap" to "did anything survive the check". Co-Scientist ranks; Kosmos checks
every statement against a source; Robin runs the experiment. Nodus does none of
the three yet. The loop in `bridge.py` is therefore reported as a mechanism
test, not as a discovery.

There is also a newer use of the word **context**: the part of a system's state
that is not shown to the reader but conditions the model (Kosmos's world model is
the clearest published case). `cells.py` implements the small honest version:
each cell has a `latent` slice of the graph that goes into the prompt and is not
rendered in the cell.

## Structural holes, and why the name is not the theory

| work | status | what Nodus does with it |
|---|---|---|
| Burt, R. S. (1992). *Structural Holes.* Harvard University Press. | **peer-reviewed** (monograph) | the idea that an absent tie between otherwise separate groups is an opportunity, not an error |
| Burt, R. S. (2004). *Structural Holes and Good Ideas.* AJS 110(2), 349–399. [doi:10.1086/421787](https://doi.org/10.1086/421787) | **peer-reviewed** | brokerage across disconnected groups exposes non-redundant information — the reason a gap is worth a card at all |
| Pachucki, M. A. & Breiger, R. L. (2010). *Cultural Holes.* Annual Review of Sociology 36, 205–224. [doi:10.1146/annurev.soc.012809.102615](https://doi.org/10.1146/annurev.soc.012809.102615) | **peer-reviewed** | a lead for holes that are about meaning rather than ties. Not implemented |

**analogy, stated plainly.** Burt's structural hole is a missing *social tie*
between people, measured by constraint on an actor's opportunity. Nodus computes
an absent *co-occurrence* between two clusters of lemmas, measured by
resource-allocation and a shuffle null. Calling ours a structural hole is a
useful shorthand and a category error if taken literally. The code says
`gap`/`porosity`/`bridged`; it does not claim Burt's constraint.

## Gaps as hypotheses rather than gaps as facts

| work | status | what it contributes |
|---|---|---|
| Swanson, D. R. (1986). *Fish Oil, Raynaud's Syndrome, and Undiscovered Public Knowledge.* Perspect Biol Med 30(1), 7–18. [doi:10.1353/pbm.1986.0087](https://doi.org/10.1353/pbm.1986.0087) | **peer-reviewed** | the A–B–C pattern: one literature links A to B, another links B to C, neither links A to C |
| Swanson & Smalheiser (1996). *Undiscovered Public Knowledge: A Ten-Year Update.* KDD '96, 295–298. [pdf](https://cdn.aaai.org/KDD/1996/KDD96-051.pdf) | **peer-reviewed** | "undiscovered" is a property of *separate* literatures, not of one document's paragraphs |
| Weeber, M. et al. (2001). *Using Concepts in Literature-Based Discovery.* JASIST 52(7), 548–557. [doi:10.1002/asi.1104](https://doi.org/10.1002/asi.1104) | **peer-reviewed** | two stages: generate candidate hypotheses, then test them. Nodus has stage one only |
| Cameron, D. et al. (2013). *A Graph-Based Recovery and Decomposition of Swanson's Hypothesis using Semantic Predications.* JBI 46(2), 238–251. [doi:10.1016/j.jbi.2012.09.004](https://doi.org/10.1016/j.jbi.2012.09.004) | **peer-reviewed** | the strongest argument for `ontology.py`: typed predications recover a mechanism that co-occurrence alone cannot. It also shows a missing edge is not a discovery until the relation is named |
| Smalheiser, N. R. (2017). *Rediscovering Don Swanson.* JDIS 2(4), 43–64. [doi:10.1515/jdis-2017-0019](https://doi.org/10.1515/jdis-2017-0019) | **peer-reviewed** (review) | the honest summary of what LBD does and does not deliver |

**What Nodus does not do.** It never searches a second corpus for the middle
term B. A gap card is a *question with evidence on both sides*, not a hypothesis
with a proposed bridge. This is why every card carries `confirm`: the falsifier
is part of the card, because a missing co-occurrence is not evidence of anything.

## Code as a graph

| work / tool | status | what it is, and what it is not |
|---|---|---|
| [Graphify](https://github.com/Graphify-Labs/graphify) (PyPI `graphifyy`, CLI `graphify`) | **tool** | tree-sitter code graph: imports, calls, inheritance, Leiden communities, local and deterministic. **No** automatic "missing link" detection, no SARIF, no issue creation. There is no tool called *graphiphy* |
| [Arcan](https://docs.arcan.tech/latest/) | **tool** | architectural-smell detection: cyclic dependency, God Component, Hub-Like Dependency, Unstable Dependency. The closest thing to a turnkey checker; not pure Python, licence terms apply |
| [Import Linter](https://import-linter.readthedocs.io/) | **tool** | Python import *contracts* — layers, forbidden imports, independence. Checks declared intent, which is exactly what a graph cannot infer |
| [dependency-cruiser](https://github.com/sverweij/dependency-cruiser), [pydeps](https://pydeps.readthedocs.io/) | **tools** | rule-based dependency validation (JS/TS) and Python import graphs. `pydeps` reads bytecode, so it cannot see a source file nothing imports |
| Wong, S., Cai, Y., Kim, M., Dalton, M. (2011). *Detecting Software Modularity Violations.* ICSE '11. [doi:10.1145/1985793.1985850](https://doi.org/10.1145/1985793.1985850) | **peer-reviewed** | Clio: compare how components *should* change together with how they *do* change together in history. Nodus has no co-change analysis — a real limitation, since git history is available |
| Zhang, Y. et al. (2023). *Software Architecture Recovery with Information Fusion.* ESEC/FSE '23. [arXiv:2311.04643](https://arxiv.org/html/2311.04643v1) | **peer-reviewed** | fuses dependencies, code text and folder structure to recover an architecture. Note the acronym collision: its technique is called SARIF, unrelated to the SARIF *report format* |
| Li, R., Liang, P., Avgeriou, P. *Towards Automated Identification of Violation Symptoms of Architecture Erosion.* [arXiv:2306.08616](https://arxiv.org/html/2306.08616v5) | **preprint** | erosion symptoms show up in review discussion, not only in static graphs |
| Traag, V., Waltman, L., van Eck, N. J. (2019). *From Louvain to Leiden.* Scientific Reports. [PMC6435756](https://pmc.ncbi.nlm.nih.gov/articles/PMC6435756/) | **peer-reviewed** | Louvain can return internally disconnected communities. A community is a partition, not a module — which is why `issues.py` treats a shared-vocabulary pair as a *candidate* |

**The rule that came out of reading these.** A graph can decide cycles, orphans,
and unused definitions inside a tree. It cannot decide that an *absent* edge was
intended. So `issues.from_code` files only decidable things as defects
(`confidence 1.0`) and marks vocabulary overlap `confidence 0.35`, with the
falsifier in `confirm`. Anything else would be invented intent.

## Tickets

| work | status | what it gives |
|---|---|---|
| GitHub REST, [issues](https://docs.github.com/en/rest/issues/issues) and [search](https://docs.github.com/en/rest/search/search) | **documentation** | list/create/comment/close, `state`, `labels`, `number`; PRs appear in the issues list and are filtered by the `pull_request` key; 5,000 req/hr authenticated, 60 unauthenticated, search 30/min |
| [Scheduling issue creation](https://docs.github.com/en/actions/tutorials/manage-your-work/schedule-issue-creation) | **documentation** | the supported pattern for filing issues from automation (`issues: write`, `GH_TOKEN`) |

Nodus reads tickets and never writes them. Filing is a human decision, and the
board is local state (`solve/issues.json`, gitignored) — closing a card does not
close a GitHub issue, deliberately, so the two cannot drift silently.
