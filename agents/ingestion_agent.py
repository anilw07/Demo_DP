"""Ingestion Build Agent — generates bronze-layer ingestion pipelines.

Reads the source objects from the ODCS contract and emits one ingestion
pipeline definition per source table (system, load type, schedule, target
Delta path), registering source→bronze lineage. In production this agent
would generate Databricks Lakeflow / ADF / Airflow pipeline code and deploy it
through CI/CD.
"""

from __future__ import annotations

import json

import yaml

from common.models import AgentResult, PipelineContext, ODCS_PATH, print_report, write_artifact

LOAD_STRATEGY = {
    "customer_account": {"load_type": "CDC", "schedule": "0 4 * * *"},
    "party_details": {"load_type": "CDC", "schedule": "0 4 * * *"},
    "transaction_details": {"load_type": "incremental-append", "schedule": "0 */4 * * *"},
    "customer_ticket_details": {"load_type": "batch-full", "schedule": "0 5 * * *"},
    "customer_product_details": {"load_type": "batch-full", "schedule": "0 5 * * *"},
}

# maps each source table to its domain key in the contract's sourceOfRecord property
TABLE_TO_SYSTEM = {
    "customer_account": "core-banking",
    "party_details": "crm",
    "transaction_details": "payments",
    "customer_ticket_details": "itsm",
    "customer_product_details": "product",
}


def run(ctx: PipelineContext) -> AgentResult:
    contract = yaml.safe_load(ODCS_PATH.read_text(encoding="utf-8"))
    source_map = {}
    for entry in contract.get("customProperties", []):
        if entry["property"] == "sourceOfRecord":
            source_map = dict(pair.strip().split(":", 1) for pair in entry["value"].split(";"))

    source_objects = [o for o in contract.get("schema", []) if "source" in o.get("tags", [])]
    findings: list[dict] = []
    artifacts: list[str] = []

    for obj in source_objects:
        name = obj["name"]
        strategy = LOAD_STRATEGY.get(name, {"load_type": "batch-full", "schedule": "0 5 * * *"})
        system_key = TABLE_TO_SYSTEM.get(name, "unknown")
        pipeline = {
            "pipeline": f"ingest_{name}",
            "source_system": f"{system_key}:{source_map.get(system_key, 'unknown')}",
            "source_object": name,
            "load_type": strategy["load_type"],
            "schedule_cron": strategy["schedule"],
            "target": obj.get("physicalName", f"bronze.{name}"),
            "target_format": "delta",
            "schema_enforcement": "contract",
            "expected_columns": [p["name"] for p in obj.get("properties", [])],
            "dq_gates": [
                q.get("metric") for p in obj.get("properties", []) for q in p.get("quality", [])
            ] + [q.get("metric") for q in obj.get("quality", [])],
        }
        artifacts.append(write_artifact(f"pipelines/ingestion/ingest_{name}.json", json.dumps(pipeline, indent=2)))
        findings.append({
            "title": f"ingest_{name}",
            "detail": f"{pipeline['load_type']} → {pipeline['target']} (cron {pipeline['schedule_cron']}, "
                      f"{len(pipeline['expected_columns'])} columns, {len(pipeline['dq_gates'])} DQ gates)",
        })

        system_node = f"src_{name}"
        bronze_node = f"bronze_{name}"
        ctx.add_node(system_node, f"Source: {name}", "source-system")
        ctx.add_node(bronze_node, f"bronze.{name}", "bronze")
        ctx.add_edge(system_node, bronze_node, "ingest")

    ctx.audit("ingestion-agent", "pipeline-generation", "SUCCESS",
              f"generated {len(source_objects)} bronze ingestion pipelines from the ODCS contract")

    result = AgentResult(
        agent="ingestion-agent",
        status="SUCCESS",
        summary=f"Generated {len(source_objects)} bronze ingestion pipeline definitions from contract schema",
        findings=findings,
        artifacts=artifacts,
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
