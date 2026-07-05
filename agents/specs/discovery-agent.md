# Discovery Agent

**Purpose** — "Check before you build." Before a new data product is commissioned, scan the enterprise ecosystem for existing data products with similar scope and for duplicate or overlapping source tables, then recommend *reuse*, *extend* or *build new*.

**Trigger** — First step of every data product initiative; invoked with the proposed product name and candidate source entities.

**Inputs**
- Proposed product definition (name + candidate source entities)
- Enterprise data catalog / data product marketplace (mocked by `common/mock_catalog.json`)

**Outputs**
- `output/discovery/discovery_report.json` — similar products with similarity scores, duplicate source tables, recommendation
- Audit event (`catalog-scan`)

**Mock behaviour** — Computes Jaccard entity-overlap against catalogued products; flags catalog tables annotated as overlapping copies (`crm_party_master`, `acct_balance_daily`).

**Production tools** — Catalog APIs (Unity Catalog, Collibra, DataHub, Purview), marketplace search, embedding-based semantic similarity over product descriptions and column profiles, column-fingerprint duplicate detection.

**Guardrails**
- Never recommends sourcing from uncertified table registrations.
- A similarity score above 70% requires a human architecture-board decision before proceeding.
