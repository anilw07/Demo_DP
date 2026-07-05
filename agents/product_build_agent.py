"""Data Product Build Agent — assembles and publishes the data product.

Verifies that all upstream artifacts exist (ODPS definition, ODCS contract,
ingestion pipelines, transformation SQL), runs mock data-quality checks
against the contract's quality rules, and publishes a product manifest with
the output ports. Registers gold→port lineage. In production this agent would
register the product in the marketplace, wire entitlements and enable
contract enforcement/monitoring.
"""

from __future__ import annotations

import json

import yaml

from common.models import (
    AgentResult, PipelineContext, ODCS_PATH, ODPS_PATH, OUTPUT_DIR, print_report, write_artifact, utc_now,
)


def _mock_dq_run(contract: dict) -> list[dict]:
    """Pretend to execute every contract quality rule; deterministic PASS results."""
    checks = []
    for obj in contract.get("schema", []):
        for rule in obj.get("quality", []):
            checks.append({"object": obj["name"], "column": None, "metric": rule.get("metric"), "result": "PASS"})
        for prop in obj.get("properties", []):
            for rule in prop.get("quality", []):
                checks.append({"object": obj["name"], "column": prop["name"], "metric": rule.get("metric"), "result": "PASS"})
    return checks


def run(ctx: PipelineContext) -> AgentResult:
    findings: list[dict] = []
    errors: list[str] = []

    required_artifacts = {
        "ODPS definition": ODPS_PATH,
        "ODCS contract": ODCS_PATH,
        "ingestion pipelines": OUTPUT_DIR / "pipelines" / "ingestion",
        "transformation SQL": OUTPUT_DIR / "pipelines" / "transformation" / "customer_360.sql",
    }
    for label, path in required_artifacts.items():
        if not path.exists():
            errors.append(f"missing prerequisite: {label} ({path})")
    if errors:
        ctx.audit("product-build-agent", "assembly", "FAILURE", "; ".join(errors))
        result = AgentResult("product-build-agent", "FAILURE", "; ".join(errors))
        print_report(result)
        return ctx.record(result)

    contract = yaml.safe_load(ODCS_PATH.read_text(encoding="utf-8"))
    odps = yaml.safe_load(ODPS_PATH.read_text(encoding="utf-8"))

    dq_checks = _mock_dq_run(contract)
    passed = sum(1 for c in dq_checks if c["result"] == "PASS")
    findings.append({"title": "Data quality gate", "detail": f"{passed}/{len(dq_checks)} contract quality rules passed (mock run)"})

    ports = odps.get("product", {}).get("dataAccess", {})
    manifest = {
        "product_id": odps["product"]["details"]["en"]["productID"],
        "name": odps["product"]["details"]["en"]["name"],
        "version": odps["product"]["details"]["en"].get("productVersion", "0.1.0"),
        "contract_id": contract.get("id"),
        "status": "published",
        "published_at": utc_now(),
        "output_ports": {
            port: {"type": cfg.get("outputPorttype"), "format": cfg.get("format"), "url": cfg.get("accessURL")}
            for port, cfg in ports.items()
        },
        "dq_gate": {"total": len(dq_checks), "passed": passed},
    }
    manifest_artifact = write_artifact("product/manifest.json", json.dumps(manifest, indent=2))
    dq_artifact = write_artifact("product/dq_results.json", json.dumps(dq_checks, indent=2))

    for port, cfg in ports.items():
        node_id = f"port_{port.lower()}"
        ctx.add_node(node_id, f"{port} port ({cfg.get('format')})", "port")
        ctx.add_edge("gold_customer_360", node_id, "publish")

    findings.append({"title": "Published ports", "detail": ", ".join(ports.keys())})
    ctx.audit("product-build-agent", "publish", "SUCCESS",
              f"product {manifest['product_id']} v{manifest['version']} published with {len(ports)} ports")

    result = AgentResult(
        agent="product-build-agent",
        status="SUCCESS",
        summary=f"Data product '{manifest['name']}' v{manifest['version']} assembled and published",
        findings=findings,
        artifacts=[manifest_artifact, dq_artifact],
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
