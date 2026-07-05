#!/usr/bin/env python3
"""Customer 360 data product build — end-to-end agent orchestration demo.

Runs the full mock agent pipeline:

    discovery → requirements (ODPS) → contract (ODCS) → ingestion
    → transformation → product build → audit & compliance → lineage → dashboard

Each agent prints its report and writes artifacts under output/.
Exits non-zero if any agent reports FAILURE.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "agents"))

from common.models import PipelineContext  # noqa: E402
import audit_compliance_agent  # noqa: E402
import contract_agent  # noqa: E402
import dashboard_agent  # noqa: E402
import discovery_agent  # noqa: E402
import ingestion_agent  # noqa: E402
import lineage_agent  # noqa: E402
import product_build_agent  # noqa: E402
import requirements_agent  # noqa: E402
import transformation_agent  # noqa: E402

PIPELINE = [
    ("1. Discovery — anything similar already in the ecosystem?", discovery_agent),
    ("2. Requirements — ODPS v4.1 data product definition", requirements_agent),
    ("3. Contract — ODCS v3.1.0 data contract", contract_agent),
    ("4. Ingestion — land 5 source tables into bronze", ingestion_agent),
    ("5. Transformation — silver conformance + gold customer_360", transformation_agent),
    ("6. Product build — real DQ gate, assemble and publish", product_build_agent),
    ("7. Audit & compliance — governance review", audit_compliance_agent),
    ("8. Lineage — end-to-end source→port lineage", lineage_agent),
    ("9. Dashboard — render the lineage + data UI", dashboard_agent),
]


def main() -> int:
    print("=" * 78)
    print("Meridian Retail Bank — Customer 360 Data Product | agent pipeline demo")
    print("=" * 78)

    ctx = PipelineContext()
    for title, agent_module in PIPELINE:
        print(f"\n{'-' * 78}\n{title}\n{'-' * 78}")
        result = agent_module.run(ctx)
        if result.status == "FAILURE":
            print(f"\n⛔ Pipeline halted: {result.agent} failed — {result.summary}")
            return 1

    print(f"\n{'=' * 78}")
    print("Pipeline complete. Artifacts written under output/:")
    for result in ctx.results.values():
        for artifact in result.artifacts:
            print(f"  - {artifact}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
