"""Lossless interchange for notebook cells and SolveIt metadata.

External notebook files remain source artifacts; imports never execute code.
Nested cells are represented using Flow-General metadata. Standard notebooks
can display them in depth-first order. Export retains original cell type,
source, outputs, execution count and unknown metadata.
"""
from __future__ import annotations
import json
from pathlib import Path
from flow_runtime import Runtime


def import_ipynb(rt: Runtime, path, *, name=None):
    doc=json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("nbformat")!=4:
        raise ValueError("only nbformat 4 supported")
    nid=rt.notebook(name or Path(path).stem)
    # Map external IDs into notebook-scoped runtime IDs.
    mapping={}
    for i, cell in enumerate(doc["cells"]):
        meta=dict(cell.get("metadata",{}))
        ext=meta.pop("flow_general",{})
        external=ext.get("id") or cell.get("id") or f"cell-{i}"
        if external in mapping:
            raise ValueError("duplicate external ID")
        parent=ext.get("parent")
        if parent is not None and parent not in mapping:
            raise ValueError("parent must precede child")
        raw=cell.get("source","")
        source="".join(raw) if isinstance(raw,list) else raw
        metadata={"ipynb":meta,"ipynb_type":cell["cell_type"],
                  "ipynb_id":cell.get("id"),"external_id":external,
                  "execution_count":cell.get("execution_count"),
                  "pinned":bool(meta.get("pinned")),
                  "skipped":bool(meta.get("skipped"))}
        cid=rt.add_cell(nid,source,kind=ext.get("kind",meta.get("type",cell["cell_type"])),
                        parent=mapping.get(parent),intent=ext.get("intent",{}),
                        metadata=metadata,outputs=cell.get("outputs",ext.get("noncode_outputs",[])))
        mapping[external]=cid
    return nid


def export_ipynb(rt: Runtime, nid, path):
    cells=[]
    def visit(parent=None):
        for c in rt.ordered(nid,parent):
            m=c["metadata"]
            typ=m.get("ipynb_type","code" if c["kind"]=="code" else "markdown")
            meta=dict(m.get("ipynb",{}))
            if c["kind"] in ("note","prompt","raw","code"):
                meta["type"]=c["kind"]
            for flag in ("pinned","skipped"):
                if m.get(flag): meta[flag]=True
            meta["flow_general"]={"id":c["id"],"parent":parent,
                                  "kind":c["kind"],"intent":c["intent"]}
            row={"id":c["id"][:64],"cell_type":typ,"metadata":meta,
                 "source":c["source"].splitlines(keepends=True)}
            if typ=="code":
                row["outputs"]=c["outputs"]
                row["execution_count"]=m.get("execution_count")
            elif c["outputs"]:
                meta["flow_general"]["noncode_outputs"]=c["outputs"]
            cells.append(row)
            visit(c["id"])
    visit()
    doc={"cells":cells,"metadata":{},"nbformat":4,"nbformat_minor":5}
    Path(path).write_text(json.dumps(doc,indent=2),encoding="utf-8")
    return doc


def import_legacy_sheet(rt: Runtime, path, *, name="legacy"):
    """Read existing delta fold through the original implementation."""
    import delta
    folded=delta.fold_cells(Path(path))
    nid=rt.notebook(name)
    for old in folded.values():
        rt.add_cell(nid,old.get("text",""),kind=old.get("role","note"),
                    metadata={"legacy":old})
    return nid
