"""
plan.py - the gaps decide how many agents and generations, needle approves.

The endless-loop problem, solved by construction instead of by hope:

    A = min(open gaps, 3)                    one lane per top gap, hard-capped
    attempts = min(2 per gap, 9)             effort scales with the work
    G = ceil(attempts / A)                   generations to spend the effort
    patience = 1                             one silent generation and we stop

Termination argument (the whole point):

    * Every generation runs at most A lanes, every lane at most one cells.step;
      G and A are fixed small integers decided BEFORE the model is asked, so
      batches <= A * G <= 9 regardless of what Qwen does - the loop cannot be
      talked into another round by its own output.
    * Cells may only stop earlier: no unbridged gaps left, or patience spent
      (a full generation that closed nothing and crossed nothing), or refusal.
    * No plan is executed unapproved: needle sees the whole budget as a card
      (targets, scores, caps, stop rules) and may approve, adjust generations
      (clamped 1..4 - never able to raise the cap), or refuse. Needle being
      down or unsure falls back to rules approving the deterministic plan,
      recorded as by="rules", never silently.

Every decision lands as a control event when a sink is given, so the approval
is walkable evidence like every other hidden decision.
"""

from __future__ import annotations

import math
import time

import cells

MAX_SUBAGENTS = 3
MAX_ATTEMPTS = 9
MAX_GENERATIONS = 4
ATTEMPTS_PER_GAP = 2
PATIENCE = 1

APPROVE_ACTIONS = [
    {
        "name": "approve",
        "description": "Run the plan exactly as written. Triggers: fine, approved, go, within budget.",
        "parameters": {"type": "object", "properties": {"note": {"type": "string"}}, "required": []},
    },
    {
        "name": "adjust",
        "description": "Change the generation count (1-4), never the lane count. Triggers: fewer, too many, too ambitious.",
        "parameters": {"type": "object", "properties": {"generations": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["generations"]},
    },
    {
        "name": "refuse",
        "description": "Do not run this plan. Triggers: wasteful, off-topic, no value, wrong target.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    },
]


def budget(gaps) -> dict:
    """Derive the run's shape from the gaps themselves. Pure, no model."""
    scored = sorted(gaps, key=lambda g: -getattr(g, "score", 0.0))
    n = len(scored)
    if n == 0:
        return {"subagents": 0, "generations": 0, "targets": [], "scores": {}, "patience": PATIENCE, "cap": 0}
    subagents = min(n, MAX_SUBAGENTS)
    attempts = min(n * ATTEMPTS_PER_GAP, MAX_ATTEMPTS)
    generations = max(1, math.ceil(attempts / subagents))
    targets = [g.id for g in scored[:subagents]]
    return {
        "subagents": subagents,
        "generations": generations,
        "targets": targets,
        "scores": {g.id: round(getattr(g, "score", 0.0), 3) for g in scored[:subagents]},
        "patience": PATIENCE,
        "cap": subagents * generations,
    }


def card(plan: dict) -> str:
    """The plan in words - the whole budget, so approval means something."""
    lanes = ", ".join(f"{gid} ({plan['scores'][gid]:.3f})" for gid in plan["targets"])
    return (
        f"Planned run: {plan['subagents']} subagents x {plan['generations']} generations, "
        f"at most {plan['cap']} draft batches. Lanes: {lanes}. "
        f"Stop rules: no unbridged gaps left; no progress for {plan['patience']} generation; "
        "generation count never exceeds 4. Approve, adjust generations, or refuse."
    )


def approval(plan: dict, use_needle: bool = True) -> dict:
    """Needle approves / adjusts / refuses. Rules approve if needle cannot rule."""
    t0 = time.time()
    if plan["subagents"] == 0:
        return {"decision": "refuse", "generations": 0, "by": "rules", "confidence": 1.0, "reason": "no open gaps", "ms": 0, "error": None}
    if use_needle:
        try:
            import localmodels

            r = localmodels.route(card(plan), tools=APPROVE_ACTIONS)
            name = (r.get("call") or {}).get("name") or "approve"
            if name not in ("approve", "adjust", "refuse"):
                name = "approve"
            args = (r.get("call") or {}).get("arguments") or {}
            gens = plan["generations"]
            if name == "adjust":
                try:
                    gens = int(args.get("generations", plan["generations"]))
                except (TypeError, ValueError):
                    gens = plan["generations"]
                gens = max(1, min(MAX_GENERATIONS, gens))
            return {
                "decision": name,
                "generations": gens,
                "by": "needle",
                "confidence": round(float(r.get("confidence") or 0.0), 3),
                "reason": str(r.get("reasoning") or args.get("reason") or "")[:200],
                "ms": int((time.time() - t0) * 1000),
                "error": None,
            }
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    else:
        err = "qwen disabled"
    return {
        "decision": "approve",
        "generations": plan["generations"],
        "by": "rules",
        "confidence": 1.0,
        "reason": "deterministic plan is already bounded; approval recorded not negotiated",
        "ms": int((time.time() - t0) * 1000),
        "error": err,
    }


def _open(cs: list) -> tuple[list, object]:
    r = cells.read(cs)
    a = r.get("analysis")
    if a is None:
        return [], None
    return [g for g in a.gaps if not g.bridged], a


def run(cs: list, mode: str = "draft", use_qwen: bool = True, use_needle: bool = True, sink=None) -> dict:
    """Plan, get approval, then run bounded lanes. Returns everything logged."""
    gaps, _ = _open(cs)
    plan = budget(gaps)
    log = [
        f"plan    {plan['subagents']} subagents x {plan['generations']} generations "
        f"· cap {plan['cap']} batches · patience {plan['patience']} · targets {plan['targets']}"
    ]
    if plan["subagents"] == 0:
        return {"plan": plan, "log": log, "stopped": "no unbridged gaps", "generations_run": 0, "cells_added": 0, "progress": []}

    ap = approval(plan, use_needle)
    log.append(f"approve {ap['decision']} by {ap['by']} @ {ap['confidence']:.2f} in {ap['ms']} ms - {ap['reason'][:90]}")
    if ap["error"]:
        log.append(f"model   approval unavailable ({ap['error'][:60]}); rules approved")
    if sink:
        sink(
            "control",
            {"who": ap["by"], "action": f"plan-{ap['decision']}", "subagents": plan["subagents"], "generations": ap["generations"], "targets": plan["targets"]},
            ap["by"],
        )
    if ap["decision"] == "refuse":
        return {"plan": plan, "approval": ap, "log": log, "stopped": "approval refused", "generations_run": 0, "cells_added": 0, "progress": []}

    generations = max(1, min(MAX_GENERATIONS, ap["generations"]))
    cells_added = 0
    batches = 0
    silent = plan["patience"]
    progress: list[dict] = []
    stopped = "generations exhausted"

    for gen in range(1, generations + 1):
        gaps, _ = _open(cs)
        if not gaps:
            log.append(f"gen{gen}    no unbridged gaps left")
            stopped = "no unbridged gaps"
            break
        ids_now = {g.id for g in gaps}
        lanes = [gid for gid in plan["targets"] if gid in ids_now] or [g.id for g in gaps[: plan["subagents"]]]
        crossed_any = False
        for gid in lanes:
            if batches >= MAX_ATTEMPTS:
                break
            batches += 1
            res = cells.step(cs, mode=mode, use_needle=False, use_qwen=use_qwen, target=gid, sink=sink)
            log.extend(f"gen{gen}  {line}" for line in res.get("log", []))
            if res.get("stopped"):
                log.append(f"gen{gen}  stopped: {res['stopped']}")
                continue
            cs.append(res["cell"])
            cells_added += 1
            if res["cell"].meta.get("crossed"):
                crossed_any = True
        gaps_after, _ = _open(cs)
        ids_after = {g.id for g in gaps_after}
        shrank = bool(ids_after < ids_now)
        progress.append({"generation": gen, "before": len(ids_now), "after": len(ids_after), "crossed": crossed_any, "batches": batches})
        if not ids_after:
            stopped = "no unbridged gaps"
            break
        if shrank or crossed_any:
            silent = plan["patience"]
        else:
            silent -= 1
            if silent <= 0:
                log.append(f"gen{gen}    no progress for {plan['patience']} generation - patience spent")
                stopped = "patience spent"
                break

    log.append(f"done    batches {batches} · generations {len(progress)} · cells {cells_added} · {stopped}")
    return {
        "plan": plan,
        "approval": ap,
        "log": log,
        "stopped": stopped,
        "generations_run": len(progress),
        "cells_added": cells_added,
        "progress": progress,
    }
