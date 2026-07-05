# Transformation Build Agent

**Purpose** — Generate the silver conformance plan (validate, standardise, deduplicate each source) and the gold build: the SQL that joins the five conformed tables into `gold.customer_360` at one-row-per-party grain, including derived features (balance aggregates, 90-day transaction behaviour, ticket/CSAT summary, product holdings, churn-risk score).

**Trigger** — After ingestion pipelines exist.

**Inputs**
- ODCS contract (source + output object schemas, grain, quality rules)
- Join specification (FK relationships declared in the contract)

**Outputs**
- `output/pipelines/transformation/transformation_plan.json` — per-table silver conformance steps + gold join plan
- `output/pipelines/transformation/customer_360.sql` — CTE-based gold build SQL
- Lineage registrations: `bronze → silver → gold` per table
- Audit event (`transformation-generation`)

**Mock behaviour** — Emits a deterministic plan and a representative Spark-SQL statement derived from the contract's FK relationships and output columns; the churn score is a transparent heuristic (low engagement + open complaints + single product).

**Production tools** — dbt model generation or Delta Live Tables, contract quality rules compiled to expectations/tests, identity-resolution service for party matching, feature-store publication.

**Guardrails**
- Gold grain must satisfy the contract uniqueness rule (`customer_360.party_id` duplicateValues = 0).
- No PII column may be derived into a lower classification.
- Generated SQL is peer-reviewed before deployment.
