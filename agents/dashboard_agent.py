"""Dashboard Agent — renders the data + lineage into a static HTML dashboard.

Reads the bronze/silver/gold/product artifacts and the in-memory lineage
graph built by the ingestion, transformation and product-build agents, and
renders a single self-contained HTML file (no external assets, no network
calls — everything, including the lineage diagram and charts, is inline
SVG/CSS/JS) so it opens directly in a browser. In production this would be
a live BI tool (e.g. a Databricks dashboard or Superset) reading the served
gold table plus a lineage backend (Marquez / Unity Catalog / Purview) rather
than a point-in-time static render.
"""

from __future__ import annotations

import html
import json
from collections import Counter

from common.models import AgentResult, PipelineContext, OUTPUT_DIR, print_report, write_artifact

LAYER_ORDER = ["source-system", "bronze", "silver", "gold", "port"]
LAYER_TITLES = {
    "source-system": "Source Systems",
    "bronze": "Bronze",
    "silver": "Silver",
    "gold": "Gold",
    "port": "Output Ports",
}
LAYER_CSS_CLASS = {
    "source-system": "src", "bronze": "brz", "silver": "slv", "gold": "gld", "port": "prt",
}
SOURCE_TABLES = [
    "customer_account", "party_details", "transaction_details",
    "customer_ticket_details", "customer_product_details",
]
ACCOUNT_STATUS_ORDER = ["ACTIVE", "DORMANT", "CLOSED"]
PRODUCT_TYPE_ORDER = ["LOAN", "CARD", "DEPOSIT", "INSURANCE"]
TICKET_STATUS_ORDER = ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]
CHURN_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


# --------------------------------------------------------------------------- helpers

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _load_json(relative_path: str):
    path = OUTPUT_DIR / relative_path
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _nice_max(value: float) -> int:
    if value <= 0:
        return 5
    target = value * 1.15
    for step in (5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 300, 400, 500, 750, 1000):
        if step >= target:
            return step
    return int(target) + 10


def _rounded_top_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    r = min(r, w / 2, max(h, 0.01))
    return (f"M{x + r:.1f},{y:.1f} H{x + w - r:.1f} "
            f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"V{y + h:.1f} H{x:.1f} V{y + r:.1f} "
            f"Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} Z")


# --------------------------------------------------------------------------- bar chart

def _bar_chart(chart_id: str, title: str, subtitle: str, categories: list[str], values: list[float],
               colors: list[str], value_suffix: str = "") -> str:
    width, height = 460, 300
    pad_l, pad_r, pad_t, pad_b = 42, 16, 16, 44
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    nice_max = _nice_max(max(values) if values else 0)
    n = len(categories)
    band = plot_w / max(n, 1)
    bar_w = min(26, band * 0.55)

    gridlines = []
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + plot_h * (1 - frac)
        tick_val = round(nice_max * frac)
        gridlines.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" class="gridline"/>'
            f'<text x="{pad_l - 8}" y="{y + 3:.1f}" class="tick-label" text-anchor="end">{tick_val}</text>'
        )

    bars, table_rows = [], []
    for i, (cat, val, color) in enumerate(zip(categories, values, colors)):
        cx = pad_l + band * i + band / 2
        bar_h = (val / nice_max) * plot_h if nice_max else 0
        y = pad_t + plot_h - bar_h
        path = _rounded_top_path(cx - bar_w / 2, y, bar_w, bar_h)
        label = f"{val:g}{value_suffix}"
        bars.append(
            f'<g class="bar-mark" tabindex="0" role="img" '
            f'aria-label="{esc(cat)}: {esc(label)}" '
            f'data-cat="{esc(cat)}" data-val="{esc(label)}">'
            f'<title>{esc(cat)}: {esc(label)}</title>'
            f'<path d="{path}" fill="{color}"/>'
            f'<text x="{cx:.1f}" y="{y - 6:.1f}" class="bar-value" text-anchor="middle">{esc(label)}</text>'
            f'<text x="{cx:.1f}" y="{pad_t + plot_h + 18:.1f}" class="cat-label" text-anchor="middle">{esc(cat)}</text>'
            f'</g>'
        )
        table_rows.append(f"<tr><td>{esc(cat)}</td><td>{esc(label)}</td></tr>")

    svg = (
        f'<svg viewBox="0 0 {width} {height}" role="group" aria-label="{esc(title)}" class="chart-svg">'
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="axis-line"/>'
        + "".join(gridlines) + "".join(bars) + "</svg>"
    )
    table = (f'<details class="table-toggle"><summary>View as table</summary>'
             f'<table class="data-table"><thead><tr><th>Category</th><th>Value</th></tr></thead>'
             f'<tbody>{"".join(table_rows)}</tbody></table></details>')
    return (f'<figure class="chart-card" id="{chart_id}">'
            f'<figcaption><span class="chart-title">{esc(title)}</span>'
            f'<span class="chart-subtitle">{esc(subtitle)}</span></figcaption>'
            f'{svg}{table}</figure>')


# --------------------------------------------------------------------------- lineage diagram

def _lineage_diagram(nodes: list[dict], edges: list[dict]) -> str:
    by_layer: dict[str, list] = {layer: [] for layer in LAYER_ORDER}
    for node in nodes:
        by_layer.setdefault(node["layer"], []).append(node)
    for layer in by_layer:
        by_layer[layer].sort(key=lambda n: n["node_id"])

    box_w, box_h, col_gap, row_gap, top_margin, side_margin = 180, 46, 90, 16, 46, 16
    max_rows = max((len(v) for v in by_layer.values()), default=1) or 1
    plot_h = max_rows * box_h + (max_rows - 1) * row_gap
    svg_h, svg_w = plot_h + top_margin + 20, side_margin * 2 + len(LAYER_ORDER) * box_w + (len(LAYER_ORDER) - 1) * col_gap

    positions: dict[str, tuple] = {}
    headers, boxes = [], []
    for i, layer in enumerate(LAYER_ORDER):
        nodes = by_layer.get(layer, [])
        col_x = side_margin + i * (box_w + col_gap)
        total_h = len(nodes) * box_h + max(len(nodes) - 1, 0) * row_gap
        start_y = top_margin + (plot_h - total_h) / 2
        css_class = LAYER_CSS_CLASS[layer]
        headers.append(
            f'<circle cx="{col_x + 7}" cy="{top_margin - 22}" r="5" class="legend-dot {css_class}"/>'
            f'<text x="{col_x + 18}" y="{top_margin - 18}" class="col-header">{esc(LAYER_TITLES[layer])}</text>'
        )
        for j, node in enumerate(nodes):
            y = start_y + j * (box_h + row_gap)
            positions[node["node_id"]] = (col_x, y)
            main, _, secondary = node["label"].partition(" (")
            if layer == "source-system":
                main = main.replace("Source: ", "")
            elif "." in main:
                main = main.split(".", 1)[1]
            secondary = secondary.rstrip(")")
            boxes.append(
                f'<g class="lnode {css_class}">'
                f'<rect x="{col_x:.1f}" y="{y:.1f}" width="{box_w}" height="{box_h}" rx="7"/>'
                f'<text x="{col_x + box_w / 2:.1f}" y="{y + 19:.1f}" class="lnode-main" text-anchor="middle">{esc(main)}</text>'
                + (f'<text x="{col_x + box_w / 2:.1f}" y="{y + 34:.1f}" class="lnode-sub" text-anchor="middle">{esc(secondary)}</text>'
                   if secondary else "")
                + "</g>"
            )

    edge_paths = []
    for edge in edges:
        if edge["source"] not in positions or edge["target"] not in positions:
            continue
        sx, sy = positions[edge["source"]]
        tx, ty = positions[edge["target"]]
        x1, y1 = sx + box_w, sy + box_h / 2
        x2, y2 = tx, ty + box_h / 2
        midx = (x1 + x2) / 2
        edge_paths.append(f'<path d="M{x1:.1f},{y1:.1f} C{midx:.1f},{y1:.1f} {midx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" '
                          f'class="edge" marker-end="url(#arrow)"/>')

    svg = (
        f'<svg viewBox="0 0 {svg_w} {svg_h}" class="lineage-svg" role="img" '
        f'aria-label="End-to-end lineage from source systems through bronze, silver, gold to output ports">'
        f'<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" class="arrowhead"/></marker></defs>'
        + "".join(headers) + "".join(edge_paths) + "".join(boxes) + "</svg>"
    )
    return f'<div class="lineage-scroll">{svg}</div>'


# --------------------------------------------------------------------------- data tables

def _records_table(records: list[dict], columns: list[str] | None = None, row_id: str | None = None,
                    limit: int | None = None) -> str:
    if not records:
        return '<p class="empty-state">No records.</p>'
    cols = columns or list(records[0].keys())
    rows = records[: limit] if limit else records
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            elif isinstance(v, bool):
                v = "true" if v else "false"
            elif v is None:
                v = "–"
            cells.append(f"<td>{esc(v)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    id_attr = f' id="{row_id}"' if row_id else ""
    return (f'<div class="table-scroll"><table class="data-table"{id_attr}>'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


# --------------------------------------------------------------------------- KPI tiles

def _stat_tile(label: str, value: str, note: str = "") -> str:
    return (f'<div class="stat-tile"><div class="stat-label">{esc(label)}</div>'
            f'<div class="stat-value">{esc(value)}</div>'
            + (f'<div class="stat-note">{esc(note)}</div>' if note else "") + "</div>")


# --------------------------------------------------------------------------- compliance / DQ panel

def _status_list(items: list[dict], label_key: str, result_key: str, detail_key: str) -> str:
    rows = []
    for item in items:
        result = item.get(result_key, "PASS")
        cls = "good" if result == "PASS" else "critical"
        icon = "✓" if result == "PASS" else "✗"
        rows.append(
            f'<li class="status-row {cls}"><span class="status-icon">{icon}</span>'
            f'<span class="status-label">{esc(item.get(label_key, ""))}</span>'
            f'<span class="status-result">{esc(result)}</span>'
            f'<span class="status-detail">{esc(item.get(detail_key, ""))}</span></li>'
        )
    return f'<ul class="status-list">{"".join(rows)}</ul>'


# --------------------------------------------------------------------------- main

def run(ctx: PipelineContext) -> AgentResult:
    required = {
        **{f"bronze/{t}.json": None for t in SOURCE_TABLES},
        **{f"silver/{t}.json": None for t in SOURCE_TABLES},
        "gold/customer_360.json": None,
        "product/manifest.json": None,
        "product/dq_results.json": None,
        "audit/compliance_report.json": None,
        "lineage/lineage.json": None,
    }
    missing = [rel for rel in required if not (OUTPUT_DIR / rel).exists()]
    if missing:
        result = AgentResult(
            "dashboard-agent", "FAILURE",
            f"Missing prerequisite artifacts {missing} — "
            "run ingestion, transformation, product-build, audit-compliance and lineage agents first",
        )
        print_report(result)
        return ctx.record(result)

    bronze = {t: _load_json(f"bronze/{t}.json") for t in SOURCE_TABLES}
    gold = _load_json("gold/customer_360.json")
    manifest = _load_json("product/manifest.json")
    dq_results = _load_json("product/dq_results.json")
    compliance = _load_json("audit/compliance_report.json")
    lineage_graph = _load_json("lineage/lineage.json")

    # ---- KPIs
    total_source_rows = sum(len(v) for v in bronze.values())
    dq_passed = sum(1 for c in dq_results if c["result"] == "PASS")
    compliance_passed = sum(1 for c in compliance if c["result"] == "PASS")
    total_aum = sum(r["total_balance_eur"] for r in gold)
    high_risk = sum(1 for r in gold if r["churn_risk_score"] >= 0.6)
    open_tickets = sum(r["open_ticket_count"] for r in gold)

    kpis = "".join([
        _stat_tile("Resolved customers", f"{len(gold)}", "customer_360 grain: 1 row / party"),
        _stat_tile("Source rows ingested", f"{total_source_rows}", f"across {len(SOURCE_TABLES)} bronze tables"),
        _stat_tile("Data quality gate", f"{dq_passed}/{len(dq_results)}", "contract rules passed"),
        _stat_tile("Compliance checks", f"{compliance_passed}/{len(compliance)}", "GDPR / BCBS 239 / residency"),
        _stat_tile("Total AUM", f"€{total_aum:,.0f}", "sum of active account balances"),
        _stat_tile("Customers at churn risk", f"{high_risk}", "churn_risk_score ≥ 0.6"),
        _stat_tile("Open service tickets", f"{open_tickets}", "OPEN or IN_PROGRESS"),
    ])

    # ---- charts
    acc_counts = Counter(a["account_status"] for a in bronze["customer_account"])
    acc_cats = [c for c in ACCOUNT_STATUS_ORDER if acc_counts.get(c)]
    chart_accounts = _bar_chart("chart-accounts", "Account status mix", "customer_account (bronze)",
                                 acc_cats, [acc_counts[c] for c in acc_cats], ["var(--accent)"] * len(acc_cats))

    active_holdings = [h for h in bronze["customer_product_details"] if h["status"] == "ACTIVE"]
    prod_counts = Counter(h["product_type"] for h in active_holdings)
    prod_cats = [c for c in PRODUCT_TYPE_ORDER if prod_counts.get(c)]
    chart_products = _bar_chart("chart-products", "Active holdings by product type", "customer_product_details (bronze)",
                                 prod_cats, [prod_counts[c] for c in prod_cats], ["var(--accent)"] * len(prod_cats))

    tkt_counts = Counter(t["status"] for t in bronze["customer_ticket_details"])
    tkt_cats = [c for c in TICKET_STATUS_ORDER if tkt_counts.get(c)]
    chart_tickets = _bar_chart("chart-tickets", "Ticket status mix", "customer_ticket_details (bronze)",
                                tkt_cats, [tkt_counts[c] for c in tkt_cats], ["var(--accent)"] * len(tkt_cats))

    churn_labels = [f"{lo:.1f}–{hi if hi <= 1 else 1.0:.1f}" for lo, hi in CHURN_BUCKETS]
    churn_counts = [sum(1 for r in gold if lo <= r["churn_risk_score"] < hi) for lo, hi in CHURN_BUCKETS]
    ordinal_colors = ["var(--ordinal-1)", "var(--ordinal-2)", "var(--ordinal-3)", "var(--ordinal-4)", "var(--ordinal-5)"]
    chart_churn = _bar_chart("chart-churn", "Churn risk score distribution", "customer_360 (gold) — lighter = lower risk",
                              churn_labels, churn_counts, ordinal_colors)

    # ---- data explorer tabs (bronze samples + silver counts + gold/product)
    bronze_tabs, bronze_panels = [], []
    for i, table in enumerate(SOURCE_TABLES):
        tab_id = f"bronze-{table}"
        active = " active" if i == 0 else ""
        bronze_tabs.append(f'<button class="tab-btn{active}" data-tab="{tab_id}">{esc(table)} '
                            f'<span class="tab-count">{len(bronze[table])}</span></button>')
        bronze_panels.append(f'<div class="tab-panel{active}" id="{tab_id}">'
                              f'{_records_table(bronze[table], limit=10)}'
                              f'<p class="table-note">Showing 10 of {len(bronze[table])} rows.</p></div>')

    gold_table = _records_table(gold, row_id="gold-table")

    # ---- compliance / DQ
    compliance_html = _status_list(compliance, "check", "result", "detail")
    dq_by_object = Counter()
    dq_pass_by_object = Counter()
    for c in dq_results:
        dq_by_object[c["object"]] += 1
        if c["result"] == "PASS":
            dq_pass_by_object[c["object"]] += 1
    dq_html = "".join(
        f'<li class="status-row good"><span class="status-icon">✓</span>'
        f'<span class="status-label">{esc(obj)}</span>'
        f'<span class="status-result">{dq_pass_by_object[obj]}/{total}</span>'
        f'<span class="status-detail">quality rules passed</span></li>'
        for obj, total in dq_by_object.items()
    )

    lineage_svg = _lineage_diagram(lineage_graph["nodes"], lineage_graph["edges"])

    html_doc = _PAGE_TEMPLATE.format(
        style=_STYLE,
        script=_SCRIPT,
        product_name=esc(manifest["name"]),
        product_version=esc(manifest["version"]),
        product_status=esc(manifest["status"]),
        contract_id=esc(manifest["contract_id"]),
        published_at=esc(manifest["published_at"]),
        kpis=kpis,
        lineage_svg=lineage_svg,
        chart_accounts=chart_accounts,
        chart_products=chart_products,
        chart_tickets=chart_tickets,
        chart_churn=chart_churn,
        bronze_tabs="".join(bronze_tabs),
        bronze_panels="".join(bronze_panels),
        gold_table=gold_table,
        gold_count=len(gold),
        compliance_html=compliance_html,
        dq_html=dq_html,
    )

    artifact = write_artifact("dashboard/index.html", html_doc)
    ctx.audit("dashboard-agent", "render", "SUCCESS",
              f"rendered dashboard with {len(gold)} customer profiles, "
              f"{len(lineage_graph['nodes'])} lineage nodes, 4 charts")

    result = AgentResult(
        agent="dashboard-agent",
        status="SUCCESS",
        summary=f"Rendered lineage + data dashboard for {len(gold)} customer_360 profiles",
        findings=[
            {"title": "Lineage diagram", "detail": f"{len(lineage_graph['nodes'])} nodes / {len(lineage_graph['edges'])} edges"},
            {"title": "Charts", "detail": "account status mix, product holdings mix, ticket status mix, churn distribution"},
            {"title": "Data explorer", "detail": f"5 bronze table samples + full gold/product table ({len(gold)} rows)"},
        ],
        artifacts=[artifact],
    )
    print_report(result)
    return ctx.record(result)


# --------------------------------------------------------------------------- page template (CSS + JS are static, no braces conflict)

_STYLE = """
:root, [data-theme="light"] {
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --accent: #2a78d6;
  --layer-source: #2a78d6; --layer-bronze: #1baf7a; --layer-silver: #eda100; --layer-gold: #008300; --layer-port: #4a3aa7;
  --ordinal-1: #86b6ef; --ordinal-2: #5598e7; --ordinal-3: #2a78d6; --ordinal-4: #1c5cab; --ordinal-5: #104281;
  --status-good: #0ca30c; --status-critical: #d03b3b;
}
[data-theme="dark"] {
  --surface-1: #1a1a19; --page: #0d0d0d;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --accent: #3987e5;
  --layer-source: #3987e5; --layer-bronze: #199e70; --layer-silver: #c98500; --layer-gold: #008300; --layer-port: #9085e9;
  --ordinal-1: #86b6ef; --ordinal-2: #5598e7; --ordinal-3: #3987e5; --ordinal-4: #1c5cab; --ordinal-5: #104281;
  --status-good: #0ca30c; --status-critical: #d03b3b;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
header.top { display: flex; align-items: center; justify-content: space-between;
  padding: 20px 28px; border-bottom: 1px solid var(--border); background: var(--surface-1); }
.title-block h1 { margin: 0 0 4px; font-size: 20px; font-weight: 600; }
.title-block .meta { color: var(--text-secondary); font-size: 13px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px;
  font-weight: 600; background: color-mix(in srgb, var(--status-good) 16%, var(--surface-1)); color: var(--status-good); }
button.theme-toggle { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
  border-radius: 8px; padding: 8px 14px; font-size: 13px; cursor: pointer; }
main { padding: 24px 28px 60px; max-width: 1280px; margin: 0 auto; }
section { margin-bottom: 36px; }
section > h2 { font-size: 15px; font-weight: 600; margin: 0 0 14px; color: var(--text-primary); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
.stat-tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px 18px; border-top: 3px solid var(--accent); }
.stat-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.stat-value { font-size: 26px; font-weight: 600; }
.stat-note { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.lineage-card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
.lineage-scroll { overflow-x: auto; }
.lineage-svg { min-width: 900px; }
.col-header { font-size: 12px; font-weight: 600; fill: var(--text-secondary); }
.legend-dot.src { fill: var(--layer-source); } .legend-dot.brz { fill: var(--layer-bronze); }
.legend-dot.slv { fill: var(--layer-silver); } .legend-dot.gld { fill: var(--layer-gold); } .legend-dot.prt { fill: var(--layer-port); }
.lnode rect { fill-opacity: 0.12; stroke-width: 1.5; }
.lnode.src rect { fill: var(--layer-source); stroke: var(--layer-source); }
.lnode.brz rect { fill: var(--layer-bronze); stroke: var(--layer-bronze); }
.lnode.slv rect { fill: var(--layer-silver); stroke: var(--layer-silver); }
.lnode.gld rect { fill: var(--layer-gold); stroke: var(--layer-gold); }
.lnode.prt rect { fill: var(--layer-port); stroke: var(--layer-port); }
.lnode-main { font-size: 12px; font-weight: 600; fill: var(--text-primary); }
.lnode-sub { font-size: 10px; fill: var(--text-muted); }
.edge { fill: none; stroke: var(--text-muted); stroke-width: 1.4; opacity: 0.55; }
.arrowhead { fill: var(--text-muted); opacity: 0.55; }
.chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 18px; }
.chart-card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 16px; margin: 0; }
.chart-card figcaption { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.chart-title { font-size: 13px; font-weight: 600; }
.chart-subtitle { font-size: 11px; color: var(--text-muted); }
.chart-svg { width: 100%; height: auto; }
.gridline { stroke: var(--grid); stroke-width: 1; }
.axis-line { stroke: var(--axis); stroke-width: 1; }
.tick-label { font-size: 10px; fill: var(--text-muted); }
.cat-label { font-size: 11px; fill: var(--text-secondary); }
.bar-value { font-size: 11px; fill: var(--text-primary); font-weight: 600; }
.bar-mark path { transition: filter 0.1s ease; }
.bar-mark:hover path, .bar-mark:focus path { filter: brightness(1.12); }
.bar-mark:focus { outline: none; }
.table-toggle { margin-top: 10px; }
.table-toggle summary { cursor: pointer; font-size: 12px; color: var(--text-secondary); }
.tabs { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.tab-btn { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-secondary);
  border-radius: 8px; padding: 7px 12px; font-size: 12px; cursor: pointer; }
.tab-btn.active { color: var(--text-primary); border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, var(--surface-1)); }
.tab-count { color: var(--text-muted); font-size: 11px; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.table-note { font-size: 11px; color: var(--text-muted); margin: 8px 2px 0; }
.table-scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }
table.data-table { border-collapse: collapse; width: 100%; font-size: 12px; }
table.data-table th, table.data-table td { padding: 7px 10px; border-bottom: 1px solid var(--border);
  text-align: left; white-space: nowrap; font-variant-numeric: tabular-nums; }
table.data-table th { color: var(--text-secondary); font-weight: 600; background: color-mix(in srgb, var(--text-primary) 4%, var(--surface-1)); }
.filter-row { margin-bottom: 12px; }
.filter-row input { width: 100%; max-width: 320px; padding: 8px 12px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary); font-size: 13px; }
.panel-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; }
.panel { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }
.panel h3 { margin: 0 0 10px; font-size: 13px; font-weight: 600; }
ul.status-list { list-style: none; margin: 0; padding: 0; }
.status-row { display: grid; grid-template-columns: 18px 1fr auto; gap: 8px; padding: 7px 0;
  border-bottom: 1px solid var(--border); font-size: 12px; align-items: baseline; }
.status-row .status-detail { grid-column: 1 / -1; color: var(--text-muted); font-size: 11px; }
.status-icon { font-weight: 700; }
.status-row.good .status-icon, .status-row.good .status-result { color: var(--status-good); }
.status-row.critical .status-icon, .status-row.critical .status-result { color: var(--status-critical); }
.status-label { font-weight: 500; }
.status-result { font-weight: 600; text-align: right; }
.empty-state { color: var(--text-muted); font-size: 12px; }
.tooltip { position: fixed; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
  font-size: 11px; padding: 4px 8px; border-radius: 6px; opacity: 0; transition: opacity 0.1s ease; z-index: 20; }
footer.foot { text-align: center; color: var(--text-muted); font-size: 11px; padding: 20px; }
"""

_SCRIPT = """
document.querySelectorAll('.tabs').forEach(function (group) {
  group.addEventListener('click', function (evt) {
    var btn = evt.target.closest('.tab-btn');
    if (!btn) return;
    var scope = group.closest('section');
    scope.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
    scope.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
    btn.classList.add('active');
    var panel = scope.querySelector('#' + btn.getAttribute('data-tab'));
    if (panel) panel.classList.add('active');
  });
});

var tooltip = document.createElement('div');
tooltip.className = 'tooltip';
document.body.appendChild(tooltip);
function showTip(el, evt) {
  var cat = el.getAttribute('data-cat'), val = el.getAttribute('data-val');
  tooltip.textContent = cat + ': ' + val;
  tooltip.style.opacity = '1';
  var x = (evt && evt.clientX) || el.getBoundingClientRect().left;
  var y = (evt && evt.clientY) || el.getBoundingClientRect().top;
  tooltip.style.left = (x + 12) + 'px';
  tooltip.style.top = (y + 12) + 'px';
}
function hideTip() { tooltip.style.opacity = '0'; }
document.querySelectorAll('.bar-mark').forEach(function (mark) {
  mark.addEventListener('pointerenter', function (evt) { showTip(mark, evt); });
  mark.addEventListener('pointermove', function (evt) { showTip(mark, evt); });
  mark.addEventListener('pointerleave', hideTip);
  mark.addEventListener('focus', function () { showTip(mark); });
  mark.addEventListener('blur', hideTip);
});

var themeToggle = document.getElementById('theme-toggle');
var root = document.documentElement;
function applyTheme(mode) {
  root.setAttribute('data-theme', mode);
  themeToggle.textContent = mode === 'dark' ? '\\u2600 Light mode' : '\\u263E Dark mode';
}
applyTheme('light');
themeToggle.addEventListener('click', function () {
  applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
});

var goldFilter = document.getElementById('gold-filter');
if (goldFilter) {
  goldFilter.addEventListener('input', function () {
    var q = goldFilter.value.trim().toLowerCase();
    document.querySelectorAll('#gold-table tbody tr').forEach(function (row) {
      row.style.display = row.textContent.toLowerCase().indexOf(q) === -1 ? 'none' : '';
    });
  });
}
"""

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{product_name} — Data Product Dashboard</title>
<style>{style}</style>
</head>
<body>
<header class="top">
  <div class="title-block">
    <h1>{product_name} <span class="badge">{product_status}</span></h1>
    <div class="meta">v{product_version} · contract {contract_id} · published {published_at}</div>
  </div>
  <button class="theme-toggle" id="theme-toggle">☾ Dark mode</button>
</header>
<main>

<section>
  <h2>Product KPIs</h2>
  <div class="stat-grid">{kpis}</div>
</section>

<section>
  <h2>End-to-end lineage</h2>
  <div class="lineage-card">{lineage_svg}</div>
</section>

<section>
  <h2>Data quality signals</h2>
  <div class="chart-grid">
    {chart_accounts}
    {chart_products}
    {chart_tickets}
    {chart_churn}
  </div>
</section>

<section>
  <h2>Data explorer — bronze (raw, landed from source)</h2>
  <div class="tabs">{bronze_tabs}</div>
  {bronze_panels}
</section>

<section>
  <h2>Data explorer — gold / data product (customer_360, {gold_count} rows)</h2>
  <div class="filter-row"><input id="gold-filter" type="text" placeholder="Filter by party id, name, risk rating…"/></div>
  {gold_table}
</section>

<section>
  <div class="panel-grid">
    <div class="panel">
      <h3>Compliance checks</h3>
      {compliance_html}
    </div>
    <div class="panel">
      <h3>Data quality by object</h3>
      <ul class="status-list">{dq_html}</ul>
    </div>
  </div>
</section>

</main>
<footer class="foot">Meridian Retail Bank — Customer 360 data product · generated by dashboard-agent (mock) · fictional demo data</footer>
<script>{script}</script>
</body>
</html>
"""


if __name__ == "__main__":
    run(PipelineContext())
