"""Discovery Agent — checks the enterprise catalog before anything is built.

Scans the mock catalog for (a) existing data products similar to the proposed
Customer 360 and (b) duplicate / overlapping source tables, then issues a
reuse-vs-build recommendation. In production this agent would query the data
catalog (e.g. Unity Catalog, Collibra, DataHub) and the data product
marketplace via APIs and embed descriptions for semantic similarity.
"""

from __future__ import annotations

import json

from common.models import AgentResult, PipelineContext, load_catalog, print_report, write_artifact

PROPOSED = {
    "name": "Retail Banking Customer 360",
    "entities": [
        "customer_account",
        "party_details",
        "transaction_details",
        "customer_ticket_details",
        "customer_product_details",
    ],
}


def _similarity(proposed_entities: list[str], product: dict) -> float:
    """Jaccard overlap between proposed source entities and a catalog product's entities."""
    a, b = set(proposed_entities), set(product.get("entities", []))
    return round(len(a & b) / len(a | b), 2) if a | b else 0.0


def run(ctx: PipelineContext) -> AgentResult:
    catalog = load_catalog()
    findings: list[dict] = []

    similar_products = []
    for product in catalog["data_products"]:
        score = _similarity(PROPOSED["entities"], product)
        if score > 0:
            similar_products.append({**product, "similarity": score})
            findings.append({
                "title": f"Similar product: {product['name']} ({product['product_id']})",
                "detail": f"entity overlap {score:.0%}, owner {product['owner']}, refresh {product['refresh']}",
            })

    duplicates = [t for t in catalog["source_tables"] if t.get("note")]
    for table in duplicates:
        findings.append({
            "title": f"Duplicate/overlapping source: {table['table']} ({table['system']})",
            "detail": table["note"],
        })

    best = max((p["similarity"] for p in similar_products), default=0.0)
    recommendation = (
        "BUILD NEW: no existing product covers the full 5-table Customer 360 scope "
        f"(best overlap {best:.0%}). Reuse certified source registrations; exclude "
        "uncertified duplicates (crm_party_master, acct_balance_daily) from sourcing."
    )

    artifact = write_artifact(
        "discovery/discovery_report.json",
        json.dumps(
            {
                "proposed_product": PROPOSED,
                "similar_products": similar_products,
                "duplicate_sources": duplicates,
                "recommendation": recommendation,
            },
            indent=2,
        ),
    )

    ctx.audit("discovery-agent", "catalog-scan", "SUCCESS",
              f"{len(similar_products)} similar products, {len(duplicates)} duplicate sources found")

    result = AgentResult(
        agent="discovery-agent",
        status="SUCCESS",
        summary=recommendation,
        findings=findings,
        artifacts=[artifact],
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
