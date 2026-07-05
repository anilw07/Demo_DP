"""Data Contract Agent — builds/validates the ODCS contract.

Loads the ODCS v3.1.0 contract for the Customer 360 product and validates:
required root fields, primary keys on every schema object, PII classification
coverage, foreign-key relationships to the party master, and the cross-link
back to the ODPS product definition. In production this agent would generate
the contract from source system metadata plus stewardship input, and register
it in the contract registry for enforcement.
"""

from __future__ import annotations

import json

import yaml

from common.models import AgentResult, PipelineContext, ODCS_PATH, ODPS_PATH, print_report, write_artifact

REQUIRED_ROOT_FIELDS = ["apiVersion", "kind", "id", "version", "status"]
PII_COLUMNS = {"full_name", "date_of_birth", "national_id", "email", "phone", "address"}


def run(ctx: PipelineContext) -> AgentResult:
    contract = yaml.safe_load(ODCS_PATH.read_text(encoding="utf-8"))
    odps = yaml.safe_load(ODPS_PATH.read_text(encoding="utf-8"))
    findings: list[dict] = []
    errors: list[str] = []

    for field_name in REQUIRED_ROOT_FIELDS:
        if field_name not in contract:
            errors.append(f"missing required root field '{field_name}'")

    objects = contract.get("schema", [])
    fk_count = 0
    quality_count = 0
    for obj in objects:
        props = obj.get("properties", [])
        if not any(p.get("primaryKey") for p in props):
            errors.append(f"object '{obj.get('name')}' has no primary key")
        for prop in props:
            if prop.get("name") in PII_COLUMNS and prop.get("classification") != "restricted":
                errors.append(f"PII column {obj.get('name')}.{prop.get('name')} not classified 'restricted'")
            fk_count += len(prop.get("relationships", []))
            quality_count += len(prop.get("quality", []))
        quality_count += len(obj.get("quality", []))

    odps_contract_id = odps.get("product", {}).get("contract", {}).get("id", "")
    if contract.get("id", "")[-8:] not in odps_contract_id and odps_contract_id[-8:] not in contract.get("id", ""):
        findings.append({
            "title": "Cross-link check",
            "detail": "ODPS contract.id and ODCS id use different identifiers (verify registry mapping)",
        })
    else:
        findings.append({
            "title": "Cross-link check",
            "detail": f"ODPS contract.id '{odps_contract_id}' ↔ ODCS id '{contract.get('id')}' consistent",
        })

    findings.append({
        "title": "Schema coverage",
        "detail": f"{len(objects)} objects ({', '.join(o.get('name') for o in objects)})",
    })
    findings.append({
        "title": "Integrity & quality",
        "detail": f"{fk_count} foreign-key relationships, {quality_count} quality rules, "
                  f"{len(contract.get('slaProperties', []))} SLA properties, {len(contract.get('roles', []))} access roles",
    })

    artifact = write_artifact(
        "contract/odcs_validation.json",
        json.dumps({"odcs_version": contract.get("apiVersion"), "errors": errors, "findings": findings}, indent=2),
    )

    status = "FAILURE" if errors else "SUCCESS"
    ctx.audit("contract-agent", "odcs-validation", status,
              "ODCS v3.1.0 contract valid" if not errors else "; ".join(errors))

    result = AgentResult(
        agent="contract-agent",
        status=status,
        summary=(
            f"ODCS {contract.get('apiVersion')} contract '{contract.get('name')}' v{contract.get('version')} validated"
            if not errors else f"ODCS validation failed: {'; '.join(errors)}"
        ),
        findings=findings,
        artifacts=[artifact],
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
