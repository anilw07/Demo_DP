# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A demo of a retail-banking **Customer 360 data product** built data-mesh style at the fictional Meridian Retail Bank. It has four coupled parts:

1. `data-product/customer-360.odps.yaml` — the data product requirement definition, authored against **ODPS v4.1** (Open Data Product Specification, opendataproducts.org).
2. `data-contract/customer-360.odcs.yaml` — the data contract, authored against **ODCS v3.1.0** (Open Data Contract Standard, Bitol / LF AI & Data). Covers 5 source tables + the `customer_360` gold output table.
3. `data/seed/*.csv` — ~100 fixed, correlated records per source table (produced once by `scripts/generate_seed_data.py`, then committed as frozen fixtures — the CSVs, not the script, are the source of truth agents read at runtime).
4. `agents/` — 9 deterministic mock Python agents (discovery → requirements → contract → ingestion → transformation → product build → audit & compliance → lineage → dashboard), each with a markdown spec in `agents/specs/`, run end-to-end by `orchestrator.py`.

All institutions and data are fictional. Agents are intentionally mock/deterministic — no LLM calls, no network, no external services (the generated dashboard HTML is also fully self-contained: inline CSS/JS/SVG, no CDN). Keep it that way unless asked otherwise.

## Commands

```bash
pip install -r requirements.txt   # PyYAML is the only dependency (Python 3.9+); csv/json/etc. are stdlib
python orchestrator.py            # run the full 9-agent pipeline; exits non-zero on any agent FAILURE
cd agents && python discovery_agent.py   # run one agent standalone (fresh PipelineContext)
python scripts/generate_seed_data.py     # regenerate data/seed/*.csv (only if replacing the fixtures)
```

There is no separate test suite or linter. **`python orchestrator.py` is the verification** — it must complete with all agents reporting SUCCESS, then open `output/dashboard/index.html` in a browser to see the result. `transformation_agent.py`, `product_build_agent.py`, `audit_compliance_agent.py`'s deeper checks, and `dashboard_agent.py` all fail standalone by design when run before their prerequisite artifacts exist (they read prior agents' outputs from `output/`, not from a passed-in context) — this is a governance gate, not a bug.

Runtime artifacts go to `output/` (git-ignored except `.gitkeep`); never commit its contents.

## Architecture

### The two YAML documents are cross-linked and agent-validated

The ODPS document and ODCS contract compose via identifiers that agents check at runtime:

- ODPS `product.contract` → `{type: ODCS, contractVersion: 3.1.0, contractURL: ../data-contract/customer-360.odcs.yaml}`; its `contract.id` (`c360-odcs-2f6a9e40`) must share the `2f6a9e40` fragment with the ODCS root `id` (contract_agent checks this).
- ODCS `customProperties.odpsProductId` → ODPS `product.details.en.productID` (`c360-retail-banking-001`).

Editing either YAML can break agent validation. The invariants enforced in code:

- **requirements_agent**: ODPS roots `schema`/`version`/`product`; `product.details.en` must have `name`, `productID`, `visibility`, `status`, `type`; contract link must be type ODCS.
- **contract_agent**: ODCS roots `apiVersion`/`kind`/`id`/`version`/`status`; every schema object needs a `primaryKey` property; every PII column (`full_name`, `date_of_birth`, `national_id`, `email`, `phone`, `address` — hardcoded in both contract_agent and audit_compliance_agent) must be `classification: restricted`.
- **audit_compliance_agent**: contract must keep a `retention` slaProperty with `driver: regulatory`, two-level approvers on every role, and `gdprLawfulBasis` / `bcbs239Criticality` / `dataResidency` customProperties.

### Agents are contract-driven and share state via PipelineContext *and* disk artifacts

`agents/common/models.py` defines the wiring: each agent's `run(ctx: PipelineContext) -> AgentResult` appends `AuditEvent`s (consumed later by audit_compliance_agent) and ingestion/transformation/build agents register `LineageNode`/`LineageEdge` entries (rendered by lineage_agent as Mermaid + JSON). The orchestrator threads one context through all 9 agents in order and halts on FAILURE. Beyond the in-memory context, later agents also read earlier agents' **persisted JSON artifacts** directly from `output/` (not just the ctx object) — this is what lets `transformation_agent.py`, `product_build_agent.py` and `dashboard_agent.py` be re-run standalone once their prerequisites exist on disk.

The ingestion and transformation agents derive their outputs (columns, DQ gates, join paths, grain) **from the ODCS contract**, not hardcoded lists — source objects are the schema entries tagged `source`, the gold table is the one named `customer_360`. Adding a source table to the contract automatically produces a new ingestion pipeline; but the static maps in `ingestion_agent.py` (`LOAD_STRATEGY`, `TABLE_TO_SYSTEM`) and `transformation_agent.py` (`SOURCE_TABLES`, `PRIMARY_KEYS`, the SQL template) must be updated to match, and a matching `data/seed/<table>.csv` fixture must exist (add it to `scripts/generate_seed_data.py`).

Paths are centralized in `common/models.py` (`REPO_ROOT`, `ODPS_PATH`, `ODCS_PATH`, `OUTPUT_DIR`, `SEED_DIR`); `orchestrator.py` makes `agents/` importable via `sys.path`, so agent modules import as `import discovery_agent` and `from common.models import ...` (not `agents.common`).

### Real bronze → silver → gold execution, not just pipeline stubs

`ingestion_agent.py` actually reads `data/seed/<table>.csv`, coerces values to the contract's `logicalType`, and writes `output/bronze/<table>.json`. `transformation_agent.py` actually dedupes bronze into `output/silver/<table>.json`, then executes (in Python, not just documented in `customer_360.sql`) the same join/aggregation logic to build `output/gold/customer_360.json` — one row per party. `product_build_agent.py` runs the contract's `quality` rules as **real checks against this data** (row counts, null checks, valid-value checks, duplicate checks, reconciliation), blocking publication on any `severity: error` failure, then publishes `output/product/customer_360.{json,csv}`.

All date-relative logic (age bands, the 90-day transaction window, the 12-month CSAT window, `profile_refreshed_ts`) is computed against `common.models.REFERENCE_DATE` (a fixed constant), not `datetime.now()` — this keeps the whole pipeline reproducible regardless of when it's run. `scripts/generate_seed_data.py` generates the seed CSVs against the same constant so windows land meaningfully; it's a one-off generator (fixed `random.Random(42)` seed) — the committed CSVs are what agents actually read, not a re-run of the script.

### Dashboard agent

`dashboard_agent.py` runs last, reading every other agent's persisted `output/` artifacts (including `lineage/lineage.json`, so it doesn't need the same in-memory `ctx` as the agent that built it) and rendering a single self-contained `output/dashboard/index.html` — inline SVG lineage diagram, bar charts, KPI tiles, data tables — with no external assets or CDN dependencies. It follows this session's `dataviz` skill conventions (fixed categorical hues by layer identity, a validated ordinal ramp for the churn-risk chart, single-hue bars for nominal categories, hover tooltips, a `<details>` table-view twin per chart, explicit dark-mode toggle). If you change what any upstream agent writes to `output/`, check whether `dashboard_agent.py`'s field lookups still match.

### Conventions

- Agent statuses are `SUCCESS | WARNING | FAILURE`; use `write_artifact()` / `write_json_artifact()` for anything written under `output/` and `print_report()` for console output.
- Each agent has a matching spec in `agents/specs/<agent>.md` (purpose, trigger, I/O, mock behaviour, production tools, guardrails) — update the spec when changing an agent's behaviour, and the tables in `agents/README.md` / `README.md` if outputs change.
