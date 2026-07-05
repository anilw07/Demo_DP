# Data Contract Agent

**Purpose** — Author and validate the **ODCS v3.1.0** data contract (`data-contract/customer-360.odcs.yaml`) covering the five consumed source tables and the produced `customer_360` gold table: schemas, classifications, quality rules, SLAs, roles and compliance metadata.

**Trigger** — After the ODPS requirement definition is validated.

**Inputs**
- ODPS definition (for the cross-link and quality/SLA objectives)
- Source system metadata (table/column profiles)
- Stewardship input (classifications, retention, lawful basis)

**Outputs**
- Validated ODCS contract (mock validates the checked-in contract)
- `output/contract/odcs_validation.json`
- Audit event (`odcs-validation`)

**Mock behaviour** — Loads the ODCS YAML and asserts: required root fields (`apiVersion`, `kind`, `id`, `version`, `status`); a primary key on every schema object; `classification: restricted` on all PII columns; and consistency of the ODPS↔ODCS identifiers. Reports FK, quality-rule, SLA and role coverage.

**Production tools** — Schema harvesting from source catalogs, JSON-Schema validation against `odcs-json-schema-v3.1.0.json`, contract registry registration, enforcement hooks (DQ engine, access management).

**Guardrails**
- No contract goes `active` with unclassified personal-data columns.
- Regulatory SLAs (retention) must carry `driver: regulatory`.
- Breaking schema changes require a major contract version bump and consumer notice.
