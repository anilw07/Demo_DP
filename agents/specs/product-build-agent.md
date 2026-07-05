# Data Product Build Agent

**Purpose** — Assemble the finished data product: verify all prerequisites exist (ODPS definition, ODCS contract, ingestion pipelines, transformation SQL), execute the contract's data-quality rules as a publication gate, and publish the product manifest with its output ports (SQL / API / File).

**Trigger** — After ingestion and transformation artifacts are generated.

**Inputs**
- ODPS definition (identity, version, output ports)
- ODCS contract (quality rules for the DQ gate)
- Generated pipeline artifacts under `output/pipelines/`

**Outputs**
- `output/product/manifest.json` — published product manifest (id, version, contract id, ports, DQ-gate result)
- `output/product/dq_results.json` — per-rule DQ results
- Lineage registrations: `gold → output ports`
- Audit event (`publish`)

**Mock behaviour** — Checks prerequisite files, "executes" every contract quality rule with deterministic PASS results, and writes the manifest from the ODPS identity + access ports.

**Production tools** — Marketplace/registry APIs for publication, entitlement provisioning (Unity Catalog grants per contract role), DQ engine execution (e.g. Soda, Great Expectations, native expectations), observability wiring (freshness/SLA monitors).

**Guardrails**
- Publication is blocked if any prerequisite is missing or any `severity: error` DQ rule fails.
- The manifest version must match the ODPS `productVersion`; republication requires a version bump.
