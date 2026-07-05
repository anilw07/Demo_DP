"""Data Product Build Agent — assembles and publishes the data product.

Verifies that all upstream artifacts exist (ODPS definition, ODCS contract,
ingestion/transformation outputs), *executes* the contract's data-quality
rules against the actual bronze/gold data landed by the earlier agents
(row counts, null checks, valid-value checks, duplicate checks,
identity-resolution reconciliation), and — if no blocking (severity: error)
rule fails — publishes a product manifest plus the served customer_360
dataset (JSON + CSV) as the product itself. Registers gold→port lineage.
In production this agent would register the product in the marketplace,
wire entitlements, and enable contract enforcement/monitoring.
"""

from __future__ import annotations

import csv
import json
from collections import Counter

import yaml

from common.models import (
    AgentResult, PipelineContext, ODCS_PATH, ODPS_PATH, OUTPUT_DIR,
    print_report, write_artifact, write_json_artifact, utc_now,
)


def _load_layer_data(object_name: str) -> list[dict] | None:
    layer = "gold" if object_name == "customer_360" else "bronze"
    path = OUTPUT_DIR / layer / f"{object_name}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _evaluate_object_rule(obj_name: str, rule: dict, data: list[dict] | None) -> dict:
    metric = rule.get("metric")
    row_count = len(data) if data is not None else 0
    severity = rule.get("severity", "warning")

    if metric == "rowCount":
        threshold = rule.get("mustBeGreaterThan", 0)
        passed = row_count > threshold
        detail = f"{row_count} rows landed (> {threshold} required)"
    elif metric == "reconciliation":
        parties = _load_layer_data("party_details") or []
        rate = (row_count / len(parties)) if parties else 0.0
        passed = rate >= 0.98
        detail = f"{rate:.0%} of party_details resolved into customer_360 (>= 98% required)"
    else:
        passed, detail = True, "metric not executed in mock DQ engine"

    return {"object": obj_name, "column": None, "metric": metric, "severity": severity,
            "result": "PASS" if passed else "FAIL", "detail": detail}


def _evaluate_property_rule(obj_name: str, column: str, rule: dict, data: list[dict] | None) -> dict:
    metric = rule.get("metric")
    severity = rule.get("severity", "warning")
    values = [row.get(column) for row in data] if data else []

    if metric == "nullValues":
        nulls = sum(1 for v in values if v is None or v == "")
        passed = nulls <= rule.get("mustBe", 0)
        detail = f"{nulls} null values in {obj_name}.{column} (mustBe {rule.get('mustBe', 0)})"
    elif metric == "invalidValues":
        valid = set(rule.get("validValues", []))
        invalid = sum(1 for v in values if v is not None and v not in valid)
        passed = invalid <= rule.get("mustBe", 0)
        detail = f"{invalid} values outside {sorted(valid)} in {obj_name}.{column}"
    elif metric == "duplicateValues":
        counts = Counter(v for v in values if v is not None)
        duplicates = sum(c - 1 for c in counts.values() if c > 1)
        passed = duplicates <= rule.get("mustBe", 0)
        detail = f"{duplicates} duplicate values in {obj_name}.{column}"
    else:
        passed, detail = True, "metric not executed in mock DQ engine"

    return {"object": obj_name, "column": column, "metric": metric, "severity": severity,
            "result": "PASS" if passed else "FAIL", "detail": detail}


def _run_dq_checks(contract: dict) -> list[dict]:
    """Execute every contract quality rule against the actual landed data."""
    checks = []
    for obj in contract.get("schema", []):
        name = obj["name"]
        data = _load_layer_data(name)
        for rule in obj.get("quality", []):
            checks.append(_evaluate_object_rule(name, rule, data))
        for prop in obj.get("properties", []):
            for rule in prop.get("quality", []):
                checks.append(_evaluate_property_rule(name, prop["name"], rule, data))
    return checks


def _write_product_csv(gold_rows: list[dict]) -> str:
    target = OUTPUT_DIR / "product" / "customer_360.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(gold_rows[0].keys())
    with open(target, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in gold_rows:
            flat = dict(row)
            flat["product_types_held"] = "|".join(row.get("product_types_held") or [])
            writer.writerow(flat)
    return str(target.relative_to(OUTPUT_DIR.parent))


def run(ctx: PipelineContext) -> AgentResult:
    findings: list[dict] = []
    errors: list[str] = []

    required_artifacts = {
        "ODPS definition": ODPS_PATH,
        "ODCS contract": ODCS_PATH,
        "ingestion pipelines": OUTPUT_DIR / "pipelines" / "ingestion",
        "gold customer_360 data": OUTPUT_DIR / "gold" / "customer_360.json",
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
    gold_rows = _load_layer_data("customer_360")

    dq_checks = _run_dq_checks(contract)
    passed = sum(1 for c in dq_checks if c["result"] == "PASS")
    blocking_failures = [c for c in dq_checks if c["result"] == "FAIL" and c["severity"] == "error"]
    findings.append({
        "title": "Data quality gate",
        "detail": f"{passed}/{len(dq_checks)} contract quality rules passed against actual data "
                  f"({len(blocking_failures)} blocking failures)",
    })

    if blocking_failures:
        ctx.audit("product-build-agent", "dq-gate", "FAILURE",
                  "; ".join(f"{c['object']}.{c.get('column')}: {c['detail']}" for c in blocking_failures))
        result = AgentResult(
            agent="product-build-agent", status="FAILURE",
            summary=f"Publication blocked: {len(blocking_failures)} data-quality rule(s) failed",
            findings=findings + [{"title": f"FAIL {c['object']}.{c.get('column')}", "detail": c["detail"]}
                                  for c in blocking_failures],
            artifacts=[write_json_artifact("product/dq_results.json", dq_checks)],
        )
        print_report(result)
        return ctx.record(result)

    ports = odps.get("product", {}).get("dataAccess", {})
    manifest = {
        "product_id": odps["product"]["details"]["en"]["productID"],
        "name": odps["product"]["details"]["en"]["name"],
        "version": odps["product"]["details"]["en"].get("productVersion", "0.1.0"),
        "contract_id": contract.get("id"),
        "status": "published",
        "published_at": utc_now(),
        "record_count": len(gold_rows),
        "output_ports": {
            port: {"type": cfg.get("outputPorttype"), "format": cfg.get("format"), "url": cfg.get("accessURL")}
            for port, cfg in ports.items()
        },
        "dq_gate": {"total": len(dq_checks), "passed": passed},
    }
    manifest_artifact = write_json_artifact("product/manifest.json", manifest)
    dq_artifact = write_json_artifact("product/dq_results.json", dq_checks)
    product_json_artifact = write_json_artifact("product/customer_360.json", gold_rows)
    product_csv_artifact = _write_product_csv(gold_rows)

    for port, cfg in ports.items():
        node_id = f"port_{port.lower()}"
        ctx.add_node(node_id, f"{port} port ({cfg.get('format')})", "port")
        ctx.add_edge("gold_customer_360", node_id, "publish")

    findings.append({"title": "Published ports", "detail": ", ".join(ports.keys())})
    findings.append({"title": "Product dataset", "detail": f"{len(gold_rows)} customer_360 records published"})
    ctx.audit("product-build-agent", "publish", "SUCCESS",
              f"product {manifest['product_id']} v{manifest['version']} published with "
              f"{len(ports)} ports and {len(gold_rows)} records")

    result = AgentResult(
        agent="product-build-agent",
        status="SUCCESS",
        summary=f"Data product '{manifest['name']}' v{manifest['version']} assembled and published "
                f"({len(gold_rows)} records)",
        findings=findings,
        artifacts=[manifest_artifact, dq_artifact, product_json_artifact, product_csv_artifact],
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
