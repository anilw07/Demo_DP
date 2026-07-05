# Dashboard Agent

**Purpose** — Render the data product's bronze/silver/gold state and end-to-end lineage into a single, self-contained HTML dashboard a human can open in a browser: no build step, no external assets, no network calls at view time.

**Trigger** — Last step of the pipeline, after audit & compliance and lineage have both run.

**Inputs** (all read from `output/`, not from the in-memory context — same convention as `product_build_agent`)
- `bronze/<table>.json` ×5, `silver/<table>.json` ×5, `gold/customer_360.json`
- `product/manifest.json`, `product/dq_results.json`
- `audit/compliance_report.json`
- `lineage/lineage.json` (written by `lineage_agent`)

**Outputs**
- `output/dashboard/index.html` — product header, KPI stat tiles, an inline-SVG lineage diagram (layers: source systems → bronze → silver → gold → output ports), four bar charts (account status mix, active holdings by product type, ticket status mix, churn-risk distribution), a tabbed bronze data explorer (10-row samples per source table), a full filterable gold/`customer_360` table (100 rows), and compliance/DQ panels.
- Audit event (`render`)

**Design system** — Built following the repo's `dataviz` skill: fixed categorical hues assigned by layer identity (with a text-labeled legend, since 3 of the 8 default hues fall below 3:1 contrast on light surfaces), a validated 5-step ordinal ramp for the churn-risk buckets, single-hue bars for nominal categories (no per-bar rainbow), hairline gridlines, per-mark hover tooltips, an accessible `<details>` table-view twin on every chart, and an explicit (not OS-driven) dark-mode toggle using the palette's dark-mode steps.

**Mock behaviour** — Pure Python string templating (no template engine, no JS framework, no charting library) — the whole file, including SVG charts and the lineage diagram, is generated server-side from the JSON artifacts above.

**Production tools** — A real BI tool (e.g. Databricks Dashboards, Superset, Power BI) reading the served gold table live, plus a lineage backend (Marquez, Unity Catalog lineage, Purview) instead of a point-in-time static render.

**Guardrails**
- Refuses to render (and reports `FAILURE`) if any prerequisite artifact is missing, rather than showing a partial or stale dashboard.
- All data stays inline in the HTML file — nothing is fetched from a CDN or API, so the dashboard works fully offline.
