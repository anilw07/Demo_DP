# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A demo of a retail-banking **Customer 360 data product** built data-mesh style at the fictional Meridian Retail Bank. It has three coupled parts:

1. `data-product/customer-360.odps.yaml` — the data product requirement definition, authored against **ODPS v4.1** (Open Data Product Specification, opendataproducts.org).
2. `data-contract/customer-360.odcs.yaml` — the data contract, authored against **ODCS v3.1.0** (Open Data Contract Standard, Bitol / LF AI & Data). Covers 5 source tables + the `customer_360` gold output table.
3. `agents/` — 8 deterministic mock Python agents (discovery → requirements → contract → ingestion → transformation → product build → audit & compliance → lineage), each with a markdown spec in `agents/specs/`, run end-to-end by `orchestrator.py`.

All institutions and data are fictional. Agents are intentionally mock/deterministic — no LLM calls, no network, no external services. Keep it that way unless asked otherwise.

## Commands

```bash
pip install -r requirements.txt   # PyYAML is the only dependency (Python 3.9+)
python orchestrator.py            # run the full 8-agent pipeline; exits non-zero on any agent FAILURE
cd agents && python discovery_agent.py   # run one agent standalone (fresh PipelineContext)
```

There is no separate test suite or linter. **`python orchestrator.py` is the verification** — it must complete with all agents reporting SUCCESS. `product_build_agent.py` and `lineage_agent.py` fail standalone by design (they need artifacts/lineage from earlier agents).

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

### Agents are contract-driven and share state via PipelineContext

`agents/common/models.py` defines the wiring: each agent's `run(ctx: PipelineContext) -> AgentResult` appends `AuditEvent`s (consumed later by audit_compliance_agent) and ingestion/transformation/build agents register `LineageNode`/`LineageEdge` entries (rendered by lineage_agent as Mermaid). The orchestrator threads one context through all 8 agents in order and halts on FAILURE.

The ingestion and transformation agents derive their outputs (columns, DQ gates, join paths, grain) **from the ODCS contract**, not hardcoded lists — source objects are the schema entries tagged `source`, the gold table is the one named `customer_360`. Adding a source table to the contract automatically produces a new ingestion pipeline; but the static maps in `ingestion_agent.py` (`LOAD_STRATEGY`, `TABLE_TO_SYSTEM`) and `transformation_agent.py` (`SOURCE_TABLES`, the SQL template) must be updated to match.

Paths are centralized in `common/models.py` (`REPO_ROOT`, `ODPS_PATH`, `ODCS_PATH`, `OUTPUT_DIR`); `orchestrator.py` makes `agents/` importable via `sys.path`, so agent modules import as `import discovery_agent` and `from common.models import ...` (not `agents.common`).

### Conventions

- Agent statuses are `SUCCESS | WARNING | FAILURE`; use `write_artifact()` for anything written under `output/` and `print_report()` for console output.
- Each agent has a matching spec in `agents/specs/<agent>.md` (purpose, trigger, I/O, mock behaviour, production tools, guardrails) — update the spec when changing an agent's behaviour, and the tables in `agents/README.md` / `README.md` if outputs change.
