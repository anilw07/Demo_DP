"""Audit & Compliance Agent — governs the whole build.

Consumes the audit-event stream emitted by every preceding agent, persists it
as an immutable audit log, and runs compliance checks against the contract
metadata: PII classification coverage, regulatory retention, access approval
chains, GDPR lawful basis and BCBS 239 criticality. In production this agent
would feed the GRC platform and block publication on FAIL.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import yaml

from common.models import AgentResult, PipelineContext, ODCS_PATH, print_report, write_artifact

PII_COLUMNS = {"full_name", "date_of_birth", "national_id", "email", "phone", "address"}


def _compliance_checks(contract: dict) -> list[dict]:
    checks = []

    unclassified = [
        f"{obj['name']}.{prop['name']}"
        for obj in contract.get("schema", [])
        for prop in obj.get("properties", [])
        if prop["name"] in PII_COLUMNS and prop.get("classification") != "restricted"
    ]
    checks.append({
        "check": "PII classification",
        "requirement": "All personal-data columns classified 'restricted'",
        "result": "PASS" if not unclassified else "FAIL",
        "detail": "all PII columns restricted" if not unclassified else f"unclassified: {unclassified}",
    })

    retention = next((s for s in contract.get("slaProperties", [])
                      if s.get("property") == "retention" and s.get("driver") == "regulatory"), None)
    checks.append({
        "check": "Regulatory retention",
        "requirement": "Retention SLA present with driver=regulatory (banking record-keeping)",
        "result": "PASS" if retention else "FAIL",
        "detail": f"{retention['value']}{retention['unit']} retention" if retention else "no regulatory retention SLA",
    })

    weak_roles = [r["role"] for r in contract.get("roles", [])
                  if not (r.get("firstLevelApprovers") and r.get("secondLevelApprovers"))]
    checks.append({
        "check": "Access approval chain",
        "requirement": "Every access role has two-level approval",
        "result": "PASS" if not weak_roles else "FAIL",
        "detail": "all roles have 2-level approval" if not weak_roles else f"single-approval roles: {weak_roles}",
    })

    custom = {c["property"]: c["value"] for c in contract.get("customProperties", [])}
    checks.append({
        "check": "GDPR lawful basis",
        "requirement": "customProperties.gdprLawfulBasis documented",
        "result": "PASS" if custom.get("gdprLawfulBasis") else "FAIL",
        "detail": custom.get("gdprLawfulBasis", "missing"),
    })
    checks.append({
        "check": "BCBS 239 criticality",
        "requirement": "customProperties.bcbs239Criticality assessed",
        "result": "PASS" if custom.get("bcbs239Criticality") else "FAIL",
        "detail": custom.get("bcbs239Criticality", "missing"),
    })
    checks.append({
        "check": "Data residency",
        "requirement": "customProperties.dataResidency declared",
        "result": "PASS" if custom.get("dataResidency") else "FAIL",
        "detail": custom.get("dataResidency", "missing"),
    })

    return checks


def run(ctx: PipelineContext) -> AgentResult:
    contract = yaml.safe_load(ODCS_PATH.read_text(encoding="utf-8"))

    audit_log = "\n".join(json.dumps(asdict(event)) for event in ctx.audit_events)
    log_artifact = write_artifact("audit/audit_log.jsonl", audit_log + ("\n" if audit_log else ""))

    checks = _compliance_checks(contract)
    failed = [c for c in checks if c["result"] == "FAIL"]
    report_artifact = write_artifact("audit/compliance_report.json", json.dumps(checks, indent=2))

    findings = [{"title": f"{c['check']} — {c['result']}", "detail": c["detail"]} for c in checks]
    findings.append({
        "title": "Audit trail",
        "detail": f"{len(ctx.audit_events)} governed actions recorded across "
                  f"{len({e.agent for e in ctx.audit_events})} agents",
    })

    status = "FAILURE" if failed else "SUCCESS"
    ctx.audit("audit-compliance-agent", "compliance-review", status,
              f"{len(checks) - len(failed)}/{len(checks)} compliance checks passed")

    result = AgentResult(
        agent="audit-compliance-agent",
        status=status,
        summary=(f"All {len(checks)} compliance checks passed; audit trail persisted"
                 if not failed else f"{len(failed)} compliance checks FAILED"),
        findings=findings,
        artifacts=[log_artifact, report_artifact],
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
