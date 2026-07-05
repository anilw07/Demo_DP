"""Lineage Agent — builds and renders end-to-end lineage.

Collects the lineage nodes/edges registered by the ingestion, transformation
and product-build agents and renders the full flow — source systems → bronze
→ silver → gold customer_360 → output ports — as a Mermaid diagram plus a
console tree. In production this agent would push OpenLineage events to a
lineage backend (e.g. Marquez, Unity Catalog lineage, Purview).
"""

from __future__ import annotations

import json
from dataclasses import asdict

from common.models import AgentResult, PipelineContext, print_report, write_artifact

LAYER_ORDER = ["source-system", "bronze", "silver", "gold", "port"]
LAYER_TITLES = {
    "source-system": "Source Systems",
    "bronze": "Bronze (raw)",
    "silver": "Silver (conformed)",
    "gold": "Gold (product)",
    "port": "Output Ports",
}


def _mermaid(ctx: PipelineContext) -> str:
    lines = ["flowchart LR"]
    for layer in LAYER_ORDER:
        nodes = [n for n in ctx.lineage_nodes.values() if n.layer == layer]
        if not nodes:
            continue
        lines.append(f'  subgraph {layer.replace("-", "_")}["{LAYER_TITLES[layer]}"]')
        for node in nodes:
            lines.append(f'    {node.node_id}["{node.label}"]')
        lines.append("  end")
    for edge in ctx.lineage_edges:
        lines.append(f"  {edge.source} -->|{edge.operation}| {edge.target}")
    return "\n".join(lines) + "\n"


def _console_tree(ctx: PipelineContext) -> str:
    outgoing: dict[str, list] = {}
    for edge in ctx.lineage_edges:
        outgoing.setdefault(edge.source, []).append(edge)

    roots = [n for n in ctx.lineage_nodes.values() if n.layer == "source-system"]
    lines: list[str] = []

    def walk(node_id: str, depth: int, seen: set[str]) -> None:
        node = ctx.lineage_nodes[node_id]
        lines.append("  " * depth + ("└─ " if depth else "") + node.label)
        if node_id in seen:  # gold fans in from many silvers; expand it once
            return
        seen.add(node_id)
        for edge in outgoing.get(node_id, []):
            walk(edge.target, depth + 1, seen)

    seen: set[str] = set()
    for root in roots:
        walk(root.node_id, 0, seen)
    return "\n".join(lines)


def run(ctx: PipelineContext) -> AgentResult:
    if not ctx.lineage_nodes:
        result = AgentResult("lineage-agent", "FAILURE",
                             "No lineage registered — run ingestion/transformation/build agents first")
        print_report(result)
        return ctx.record(result)

    mermaid_artifact = write_artifact("lineage/lineage.mmd", _mermaid(ctx))
    graph_artifact = write_artifact("lineage/lineage.json", json.dumps({
        "nodes": [asdict(n) for n in ctx.lineage_nodes.values()],
        "edges": [asdict(e) for e in ctx.lineage_edges],
    }, indent=2))

    print("\n  End-to-end lineage (source → bronze → silver → gold → ports):")
    print("  " + "\n  ".join(_console_tree(ctx).splitlines()))

    layer_counts = {layer: sum(1 for n in ctx.lineage_nodes.values() if n.layer == layer)
                    for layer in LAYER_ORDER}
    ctx.audit("lineage-agent", "lineage-render", "SUCCESS",
              f"{len(ctx.lineage_nodes)} nodes / {len(ctx.lineage_edges)} edges rendered")

    result = AgentResult(
        agent="lineage-agent",
        status="SUCCESS",
        summary=f"End-to-end lineage rendered: {len(ctx.lineage_nodes)} nodes, {len(ctx.lineage_edges)} edges",
        findings=[{"title": "Nodes per layer",
                   "detail": ", ".join(f"{LAYER_TITLES[k]}: {v}" for k, v in layer_counts.items() if v)}],
        artifacts=[mermaid_artifact, graph_artifact],
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
