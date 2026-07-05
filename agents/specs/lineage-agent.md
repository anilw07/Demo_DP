# Lineage Agent

**Purpose** — Build and render the end-to-end lineage of the data product: source systems → bronze → silver → gold `customer_360` → output ports, so consumers, auditors and impact analysis all see the same picture.

**Trigger** — Last step of the pipeline, after all lineage registrations are in.

**Inputs**
- Lineage nodes/edges registered by the ingestion (`ingest`), transformation (`conform`, `join`) and product-build (`publish`) agents

**Outputs**
- `output/lineage/lineage.mmd` — Mermaid `flowchart LR` grouped by layer (renderable in GitHub, VS Code, mermaid.live)
- `output/lineage/lineage.json` — machine-readable node/edge graph
- Console lineage tree
- Audit event (`lineage-render`)

**Mock behaviour** — Renders whatever the upstream agents registered; fails explicitly if no lineage exists (i.e., run standalone without the pipeline).

**Production tools** — OpenLineage event emission to Marquez / Unity Catalog lineage / Microsoft Purview, column-level lineage from SQL parsing, impact-analysis queries ("what breaks if party_details changes?").

**Guardrails**
- Lineage is derived from what agents actually did (registered edges), never hand-drawn.
- A published product without complete source→port lineage is a governance finding.
