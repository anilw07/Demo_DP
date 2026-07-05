# Audit & Compliance Agent

**Purpose** — Provide continuous governance over the build: persist an immutable audit trail of every governed agent action, and run compliance checks against the contract metadata before/after publication.

**Trigger** — After product publication (and on a recurring schedule in production).

**Inputs**
- Audit-event stream emitted by every agent in the pipeline
- ODCS contract (classifications, SLAs, roles, custom compliance properties)

**Compliance checks (mock)**
1. **PII classification** — every personal-data column is `classification: restricted`
2. **Regulatory retention** — a retention SLA with `driver: regulatory` exists (banking record-keeping, 7y)
3. **Access approval chain** — every role has two-level approval
4. **GDPR lawful basis** — `customProperties.gdprLawfulBasis` documented
5. **BCBS 239 criticality** — `customProperties.bcbs239Criticality` assessed
6. **Data residency** — `customProperties.dataResidency` declared

**Outputs**
- `output/audit/audit_log.jsonl` — one JSON line per governed action (agent, action, outcome, detail, timestamp)
- `output/audit/compliance_report.json` — PASS/FAIL per check
- Audit event (`compliance-review`)

**Production tools** — GRC platform integration, access-log analytics (who queried PII, with which entitlement), consent verification against the CRM consent store, periodic recertification campaigns, incident workflow on FAIL.

**Guardrails**
- Any FAIL blocks publication (pipeline halts) and opens a governance incident.
- The audit log is append-only; agents cannot modify past events.
