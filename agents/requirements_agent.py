"""Data Product Requirements Agent — builds/validates the ODPS definition.

Loads the ODPS v4.1 document for the Customer 360 product, validates the
standard's required fields (schema, version, product identity), and produces a
requirements summary for downstream agents. In production this agent would
draft the ODPS YAML from a business brief plus the discovery report, and open
a review with the data product owner.
"""

from __future__ import annotations

import json

import yaml

from common.models import AgentResult, PipelineContext, ODPS_PATH, print_report, write_artifact

REQUIRED_DETAIL_FIELDS = ["name", "productID", "visibility", "status", "type"]


def run(ctx: PipelineContext) -> AgentResult:
    doc = yaml.safe_load(ODPS_PATH.read_text(encoding="utf-8"))
    findings: list[dict] = []
    errors: list[str] = []

    for field_name in ("schema", "version", "product"):
        if field_name not in doc:
            errors.append(f"missing required root field '{field_name}'")

    details = doc.get("product", {}).get("details", {}).get("en", {})
    for field_name in REQUIRED_DETAIL_FIELDS:
        if field_name not in details:
            errors.append(f"missing product.details.en.{field_name}")

    contract_link = doc.get("product", {}).get("contract", {})
    if contract_link.get("type") != "ODCS":
        errors.append("product.contract must link an ODCS contract")

    strategy = doc.get("product", {}).get("productStrategy", {})
    findings.append({
        "title": "Product identity",
        "detail": f"{details.get('name')} [{details.get('productID')}] v{details.get('productVersion')} — status {details.get('status')}",
    })
    findings.append({
        "title": "Strategy",
        "detail": f"{len(strategy.get('objectives', []))} objectives, {len(strategy.get('productKPIs', []))} product KPIs, "
                  f"business KPI: {strategy.get('contributesToKPI', {}).get('name')}",
    })
    findings.append({
        "title": "Output ports",
        "detail": ", ".join(doc.get("product", {}).get("dataAccess", {}).keys()) or "none",
    })
    findings.append({
        "title": "Contract link",
        "detail": f"{contract_link.get('type')} v{contract_link.get('contractVersion')} → {contract_link.get('contractURL')}",
    })

    summary_artifact = write_artifact(
        "requirements/odps_validation.json",
        json.dumps({"odps_version": doc.get("version"), "errors": errors, "findings": findings}, indent=2),
    )

    status = "FAILURE" if errors else "SUCCESS"
    ctx.audit("requirements-agent", "odps-validation", status,
              "ODPS v4.1 document valid" if not errors else "; ".join(errors))

    result = AgentResult(
        agent="requirements-agent",
        status=status,
        summary=(
            f"ODPS v{doc.get('version')} requirement definition validated for "
            f"'{details.get('name')}'" if not errors
            else f"ODPS validation failed: {'; '.join(errors)}"
        ),
        findings=findings,
        artifacts=[summary_artifact],
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
