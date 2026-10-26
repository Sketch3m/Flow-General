"""
dialog.py - SolveIt's dialogue model, with one deliberate change.

Answer.AI's SolveIt stores a *dialog* rather than a notebook: an ordered list of
messages, each one a note, a code cell, a prompt, or raw text, serialised as an
.ipynb. Three metadata flags do the real work there, and they are reproduced
here because they are what make the format a document rather than a chat log:

    skipped   the message exists but is hidden from the model's context
    pinned    the message survives context truncation
    is_ai_res marks an output as the model's reply to a prompt

SolveIt assembles context positionally - messages above the prompt you are
answering, nothing below it - and when the dialog outgrows the window it
**drops old unpinned messages from the top**. There is no summarisation.
(Verified against AnswerDotAI/aidialog and the SolveIt feature guide.)

That eviction is the gap this file fills. Nothing is thrown away here: an
oversized message stays in the file at full fidelity, where the background
agents can read it, and what goes into the context window is the gist - the few
statements that touch what you are currently asking about. Same format, same
flags, no data loss.

The document lives on disk as the .ipynb. That *is* the ledger; there is no
second store to drift out of sync.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import gist
import nodus

TYPES = ("note", "prompt", "code", "raw")
CHARS_PER_TOKEN = 4  # good enough for budgeting; not a tokeniser claim

_FENCE = re.compile(r"^:::\s*(\w*)\s*$", re.M)
# the legacy SolveIt prompt encoding: prompt and reply in one markdown cell
_LEGACY_SEP = re.compile(r"\n+#{0,6}\s*.*SOLVEIT_SEPARATOR_\w*\s*\n?")


def _mid() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Message:
    type: str
    source: str
    id: str = field(default_factory=_mid)
    outputs: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ValueError(f"unknown message type {self.type!r}; expected one of {TYPES}")

    # -- the two flags that matter ----------------------------------------
    @property
    def skipped(self) -> bool:
        return bool(self.metadata.get("skipped"))

    @property
    def pinned(self) -> bool:
        return bool(self.metadata.get("pinned"))

    @property
    def reply(self) -> str:
        """The model's answer, stored as an output - never as a new message."""
        for out in self.outputs:
            if out.get("metadata", {}).get("is_ai_res"):
                data = out.get("data", {})
                for key in ("text/markdown", "text/plain"):
                    if key in data:
                        v = data[key]
                        return "".join(v) if isinstance(v, list) else v
        return ""

    @property
    def body(self) -> str:
        """Source plus reply: what a reader sees for one message."""
        return self.source if not self.reply else f"{self.source}\n\n{self.reply}"

    def toggle(self, flag: str, value: bool | None = None) -> bool:
        if flag not in ("skipped", "pinned"):
            raise ValueError(flag)
        self.metadata[flag] = (not self.metadata.get(flag, False)) if value is None else value
        return bool(self.metadata[flag])


@dataclass
class Slot:
    """One message as it appears in a model's context window."""

    id: str
    type: str
    text: str
    full_chars: int
    mode: str  # "full" | "gist" | "pointer"
    excerpt: gist.Gist | None = None


@dataclass
class Context:
    slots: list[Slot] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    budget: int = 0

    @property
    def chars(self) -> int:
        return sum(len(s.text) for s in self.slots)

    @property
    def compressed(self) -> list[Slot]:
        return [s for s in self.slots if s.mode != "full"]

    def summary(self) -> dict:
        return {
            "messages in context": len(self.slots),
            "compressed": len(self.compressed),
            "dropped": len(self.dropped),
            "chars": self.chars,
            "tokens est": self.chars // CHARS_PER_TOKEN,
            "budget": self.budget,
            "kept %": round(100 * self.chars / max(1, sum(s.full_chars for s in self.slots)), 1),
        }

    def render(self) -> str:
        """What a model would actually be handed. This is the honest artefact."""
        out = []
        for s in self.slots:
            if s.mode == "pointer":
                out.append(f"[{s.type} {s.id}: {s.full_chars} chars, not relevant to this "
                           f"question, retrievable in full]")
            else:
                out.append(f"[{s.type} {s.id}]\n{s.text}")
        return "\n\n".join(out)


@dataclass
class Dialog:
    messages: list[Message] = field(default_factory=list)
    name: str = "dialog"

    # -- authoring ---------------------------------------------------------
    def add(self, type: str, source: str, **meta) -> Message:
        m = Message(type=type, source=source.strip("\n"), metadata=dict(meta))
        self.messages.append(m)
        return m

    def get(self, msg_id: str) -> Message | None:
        return next((m for m in self.messages if m.id == msg_id), None)

    def of_type(self, type: str) -> list[Message]:
        return [m for m in self.messages if m.type == type]

    def stats(self) -> dict:
        return {
            "messages": len(self.messages),
            "notes": len(self.of_type("note")),
            "prompts": len(self.of_type("prompt")),
            "skipped": sum(m.skipped for m in self.messages),
            "pinned": sum(m.pinned for m in self.messages),
            "chars": sum(len(m.body) for m in self.messages),
            "tokens est": sum(len(m.body) for m in self.messages) // CHARS_PER_TOKEN,
        }

    # -- the rule SolveIt uses, then the change ---------------------------
    def eligible(self, upto: str | None = None) -> list[Message]:
        """Messages above and including `upto`, with `skipped` removed.

        Positional, exactly as documented: a prompt cannot see below itself.
        """
        msgs = self.messages
        if upto is not None:
            idx = next((i for i, m in enumerate(msgs) if m.id == upto), len(msgs) - 1)
            msgs = msgs[: idx + 1]
        return [m for m in msgs if not m.skipped]

    def context(
        self,
        upto: str | None = None,
        budget_chars: int = 6000,
        focus: tuple[list[str], list[str]] | None = None,
    ) -> Context:
        """Build a context window, compressing rather than evicting.

        The focus defaults to the concepts of the message being answered - so
        old text is compressed *toward the current question*, not toward its own
        keywords. That is the whole trick: the reader's gap is the compressor.
        """
        msgs = self.eligible(upto)
        ctx = Context(budget=budget_chars)
        if not msgs:
            return ctx

        if focus is None:
            here = self.get(upto) if upto else msgs[-1]
            focus = (nodus.concepts(here.source)[:12] if here else [], [])
        fa, fb = focus

        for m in msgs:
            ctx.slots.append(Slot(m.id, m.type, m.body, len(m.body), "full"))
        if ctx.chars <= budget_chars:
            return ctx

        # Pinned messages are never touched. Everything else is compressed from
        # the oldest upward - except a prompt's own question, which is what is
        # being asked and so is never allowed to shrink. Only its reply is.
        for slot in ctx.slots:
            msg = self.get(slot.id)
            if msg is None or msg.pinned:
                continue
            anchor = msg.source if msg.type == "prompt" else ""
            body = msg.reply if msg.type == "prompt" else msg.body
            g = gist.gist(body, fa, fb, k=2)
            if g.unrelated or not g.chosen:
                slot.mode = "gist" if anchor else "pointer"
                slot.text, slot.excerpt = anchor, g
            else:
                slot.mode = "gist"
                slot.text = f"{anchor}\n\n{g.text}" if anchor else g.text
                slot.excerpt = g
            if ctx.chars <= budget_chars:
                break

        # only if compression was not enough: drop, oldest first, still on disk
        while ctx.chars > budget_chars and len(ctx.slots) > 1:
            victim = next(
                (s for s in ctx.slots if not (m := self.get(s.id)) or not m.pinned), None
            )
            if victim is None:
                break
            ctx.slots.remove(victim)
            ctx.dropped.append(victim.id)
        return ctx

    # -- io ----------------------------------------------------------------
    def to_ipynb(self) -> dict:
        cells = []
        for m in self.messages:
            md = {k: v for k, v in m.metadata.items() if k in ("skipped", "pinned")}
            if m.type == "note":
                cells.append(
                    {"cell_type": "markdown", "id": m.id, "metadata": {**md, "solveit_ai": False},
                     "source": m.source}
                )
            elif m.type == "prompt":
                outputs = []
                if m.reply:
                    outputs.append(
                        {
                            "output_type": "display_data",
                            "data": {"text/markdown": m.reply},
                            "metadata": {"is_ai_res": True},
                        }
                    )
                cells.append(
                    {
                        "cell_type": "code",
                        "id": m.id,
                        "metadata": {**md, "solveit_ai": True},
                        "execution_count": None,
                        "outputs": outputs,
                        "source": f"%%prompt\n{m.source}",
                    }
                )
            elif m.type == "code":
                cells.append(
                    {
                        "cell_type": "code",
                        "id": m.id,
                        "metadata": md,
                        "execution_count": None,
                        "outputs": m.outputs,
                        "source": m.source,
                    }
                )
            else:
                cells.append({"cell_type": "raw", "id": m.id, "metadata": md, "source": m.source})
        return {
            "cells": cells,
            "metadata": {
                "kernelspec": {"name": "python3", "display_name": "Python 3"},
                "nodus": {"format": "dialog/1", "name": self.name},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }

    @classmethod
    def from_ipynb(cls, nb: dict) -> "Dialog":
        d = cls(name=nb.get("metadata", {}).get("nodus", {}).get("name", "dialog"))
        for cell in nb.get("cells", []):
            src = cell.get("source", "")
            src = "".join(src) if isinstance(src, list) else src
            meta = cell.get("metadata", {}) or {}
            flags = {k: meta[k] for k in ("skipped", "pinned") if k in meta}
            kind = cell.get("cell_type")
            if kind == "code" and src.lstrip().startswith("%%prompt"):
                body = src.lstrip()[len("%%prompt"):].lstrip("\n")
                reply = ""
                for out in cell.get("outputs", []):
                    if out.get("metadata", {}).get("is_ai_res"):
                        v = out.get("data", {}).get("text/markdown", "")
                        reply = "".join(v) if isinstance(v, list) else v
                outputs = (
                    [{"output_type": "display_data", "data": {"text/markdown": reply},
                      "metadata": {"is_ai_res": True}}] if reply else []
                )
                d.messages.append(Message("prompt", body, cell.get("id") or _mid(), outputs, flags))
            elif kind == "code":
                d.messages.append(
                    Message("code", src, cell.get("id") or _mid(), cell.get("outputs", []) or [], flags)
                )
            elif kind == "raw":
                d.messages.append(Message("raw", src, cell.get("id") or _mid(), [], flags))
            else:
                # legacy encoding: prompt and reply in one markdown cell
                if meta.get("solveit_ai") and _LEGACY_SEP.search(src):
                    prompt, _, reply = _LEGACY_SEP.split(src, maxsplit=1)
                    outputs = (
                        [{"output_type": "display_data", "data": {"text/markdown": reply.strip()},
                          "metadata": {"is_ai_res": True}}] if reply.strip() else []
                    )
                    d.messages.append(
                        Message("prompt", prompt.strip(), cell.get("id") or _mid(), outputs, flags)
                    )
                elif meta.get("solveit_ai"):
                    d.messages.append(Message("prompt", src, cell.get("id") or _mid(), [], flags))
                else:
                    d.messages.append(Message("note", src, cell.get("id") or _mid(), [], flags))
        return d

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_ipynb(), indent=1))
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Dialog":
        return cls.from_ipynb(json.loads(Path(path).read_text()))


# ---------------------------------------------------------------------------
# the authoring dialect: prose is notes, ::: blocks are the rest
# ---------------------------------------------------------------------------

def parse(text: str, name: str = "dialog") -> Dialog:
    """Markdown -> Dialog.

    Plain prose is the document: each paragraph becomes a `note` message, which
    keeps the writing surface free of syntax. Only the message types that
    cannot be inferred need a fence:

        ::: prompt      the question you asked the model
        ::: reply       the model's long answer (attaches to the prompt above)
        ::: code        runnable code
        ::: raw         passed through untouched

    A `{skipped}` or `{pinned}` marker on the fence line sets the flag.
    """
    d = Dialog(name=name)
    buf: list[str] = []
    cur: tuple[str, dict] | None = None
    block: list[str] = []

    def flush_prose() -> None:
        chunk = "\n".join(buf).strip("\n")
        for para in re.split(r"\n\s*\n", chunk):
            if para.strip():
                d.add("note", para)
        buf.clear()

    def flush_block() -> None:
        nonlocal cur
        if not cur:
            return
        kind, flags = cur
        body = "\n".join(block).strip("\n")
        if kind == "reply":
            target = next((m for m in reversed(d.messages) if m.type == "prompt"), None)
            if target is not None:
                target.outputs = [
                    {"output_type": "display_data", "data": {"text/markdown": body},
                     "metadata": {"is_ai_res": True}}
                ]
                target.metadata.update(flags)
        elif body.strip():
            d.add(kind, body, **flags)
        block.clear()
        cur = None

    for line in text.splitlines():
        m = _FENCE.match(line)
        if m:
            head = m.group(1)
            if not head:  # a bare ::: closes the open block
                flush_block()
                continue
            flush_block()
            if buf:
                flush_prose()
            flags: dict = {}
            for flag in ("skipped", "pinned"):
                if flag in head:
                    flags[flag] = True
                    head = head.replace(flag, "").strip("_ ")
            cur = (head, flags)
            continue
        (block if cur else buf).append(line)
    flush_block()
    flush_prose()
    return d


def dump(d: Dialog) -> str:
    """Dialog -> the editable markdown dialect (replies included, marked)."""
    out: list[str] = []
    for m in d.messages:
        flags = "".join(f"_{k}" for k in ("skipped", "pinned") if m.metadata.get(k))
        if m.type == "note" and not flags:
            out.append(m.source)
        elif m.type == "prompt":
            out.append(f"::: prompt{flags}\n{m.source}\n:::")
            if m.reply:
                out.append(f"::: reply\n{m.reply}\n:::")
        else:
            out.append(f"::: {m.type}{flags}\n{m.source}\n:::")
    return "\n\n".join(out) + "\n"
