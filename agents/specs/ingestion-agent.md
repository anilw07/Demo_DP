# Ingestion Build Agent

**Purpose** — Generate the bronze-layer ingestion pipelines for every *source* object declared in the data contract: source system, load strategy, schedule, target Delta table, expected columns and data-quality gates.

**Trigger** — After the ODCS contract is validated.

**Inputs**
- ODCS contract `schema` objects tagged `source`
- `sourceOfRecord` custom property (system-of-record mapping)
- Load-strategy policy (CDC vs incremental vs batch)

**Outputs**
- `output/pipelines/ingestion/ingest_<table>.json` — one pipeline definition per source table
- Lineage registrations: `source-system → bronze` per table
- Audit event (`pipeline-generation`)

**Mock behaviour** — Derives each pipeline purely from the contract (columns, physical names, quality metrics become DQ gates) plus a static load-strategy map (CDC for account/party masters, 4-hourly incremental append for transactions, daily batch for tickets/holdings).

**Production tools** — Databricks Lakeflow / Auto Loader, Azure Data Factory or Airflow DAG generation, CI/CD deployment, schema-drift alerts wired to contract enforcement.

**Guardrails**
- Pipelines enforce the contract schema on write (`schema_enforcement: contract`); drift quarantines the load.
- Only certified source registrations (per discovery agent) may be ingested.
