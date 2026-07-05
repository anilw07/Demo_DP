"""Shared data structures for the Customer 360 mock agent ecosystem.

Every agent returns an AgentResult and appends AuditEvents to a shared
PipelineContext. Ingestion / transformation / build agents also register
LineageNode / LineageEdge entries that the lineage agent renders at the end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"
SEED_DIR = REPO_ROOT / "data" / "seed"
ODPS_PATH = REPO_ROOT / "data-product" / "customer-360.odps.yaml"
ODCS_PATH = REPO_ROOT / "data-contract" / "customer-360.odcs.yaml"
CATALOG_PATH = Path(__file__).resolve().parent / "mock_catalog.json"

# Fixed "as of" date for every derived/relative calculation (age bands, 90-day
# transaction windows, 12-month CSAT windows, profile refresh timestamps) so
# the pipeline is reproducible regardless of when it is actually run.
REFERENCE_DATE = date(2026, 7, 5)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AuditEvent:
    """A single governed action recorded by an agent."""

    agent: str
    action: str
    outcome: str  # SUCCESS | WARNING | FAILURE
    detail: str
    timestamp: str = field(default_factory=utc_now)


@dataclass
class LineageNode:
    node_id: str
    label: str
    layer: str  # source-system | bronze | silver | gold | port


@dataclass
class LineageEdge:
    source: str
    target: str
    operation: str  # ingest | conform | join | publish


@dataclass
class AgentResult:
    agent: str
    status: str  # SUCCESS | WARNING | FAILURE
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineContext:
    """Mutable state threaded through the orchestrated agent run."""

    audit_events: list[AuditEvent] = field(default_factory=list)
    lineage_nodes: dict[str, LineageNode] = field(default_factory=dict)
    lineage_edges: list[LineageEdge] = field(default_factory=list)
    results: dict[str, AgentResult] = field(default_factory=dict)

    def audit(self, agent: str, action: str, outcome: str, detail: str) -> None:
        self.audit_events.append(AuditEvent(agent, action, outcome, detail))

    def add_node(self, node_id: str, label: str, layer: str) -> None:
        self.lineage_nodes.setdefault(node_id, LineageNode(node_id, label, layer))

    def add_edge(self, source: str, target: str, operation: str) -> None:
        self.lineage_edges.append(LineageEdge(source, target, operation))

    def record(self, result: AgentResult) -> AgentResult:
        self.results[result.agent] = result
        return result


def load_catalog() -> dict[str, Any]:
    with open(CATALOG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def write_artifact(relative_path: str, content: str) -> str:
    """Write a text artifact under output/ and return its repo-relative path."""
    target = OUTPUT_DIR / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target.relative_to(REPO_ROOT))


def write_json_artifact(relative_path: str, records: Any) -> str:
    """Write a JSON artifact under output/ and return its repo-relative path."""
    return write_artifact(relative_path, json.dumps(records, indent=2, default=str))


def print_report(result: AgentResult) -> None:
    icon = {"SUCCESS": "✅", "WARNING": "⚠️ ", "FAILURE": "❌"}.get(result.status, "•")
    print(f"\n{icon} [{result.agent}] {result.status}: {result.summary}")
    for finding in result.findings:
        print(f"   - {finding.get('title', '')}: {finding.get('detail', '')}")
    for artifact in result.artifacts:
        print(f"   ↳ artifact: {artifact}")
