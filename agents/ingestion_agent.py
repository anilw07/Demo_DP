"""Ingestion Build Agent — generates and *runs* bronze-layer ingestion.

Reads the source objects from the ODCS contract and, for each one, emits an
ingestion pipeline definition (system, load type, schedule, target Delta
path) and actually lands the corresponding seed data (data/seed/<table>.csv)
into a bronze JSON artifact, coercing values to the contract's logicalType
and registering source→bronze lineage. In production this agent would
generate Databricks Lakeflow / ADF / Airflow pipeline code and execute it
against the real source systems rather than a fixed CSV fixture.
"""

from __future__ import annotations

import csv
import json

import yaml

from common.models import (
    AgentResult, PipelineContext, ODCS_PATH, SEED_DIR, print_report, write_artifact, write_json_artifact,
)

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


def _coerce_value(raw: str, logical_type: str):
    if raw == "" or raw is None:
        return None
    if logical_type == "boolean":
        return raw.strip().lower() == "true"
    if logical_type == "integer":
        return int(raw)
    if logical_type == "number":
        return float(raw)
    return raw


def _land_source_table(obj: dict) -> tuple[list[dict], list[str]]:
    """Read data/seed/<table>.csv, coerce to contract logicalTypes, return (rows, errors)."""
    name = obj["name"]
    seed_path = SEED_DIR / f"{name}.csv"
    type_map = {p["name"]: p.get("logicalType", "string") for p in obj.get("properties", [])}
    errors: list[str] = []

    if not seed_path.exists():
        return [], [f"missing seed fixture {seed_path.name}"]

    with open(seed_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing_columns = set(type_map) - set(reader.fieldnames or [])
        if missing_columns:
            errors.append(f"seed fixture missing contract columns: {sorted(missing_columns)}")
        rows = [
            {col: _coerce_value(value, type_map.get(col, "string")) for col, value in row.items()}
            for row in reader
        ]
    return rows, errors


def run(ctx: PipelineContext) -> AgentResult:
    contract = yaml.safe_load(ODCS_PATH.read_text(encoding="utf-8"))
    source_map = {}
    for entry in contract.get("customProperties", []):
        if entry["property"] == "sourceOfRecord":
            source_map = dict(pair.strip().split(":", 1) for pair in entry["value"].split(";"))

    source_objects = [o for o in contract.get("schema", []) if "source" in o.get("tags", [])]
    findings: list[dict] = []
    artifacts: list[str] = []
    landing_errors: list[str] = []
    total_rows = 0

    for obj in source_objects:
        name = obj["name"]
        strategy = LOAD_STRATEGY.get(name, {"load_type": "batch-full", "schedule": "0 5 * * *"})
        system_key = TABLE_TO_SYSTEM.get(name, "unknown")

        rows, errors = _land_source_table(obj)
        landing_errors.extend(f"{name}: {e}" for e in errors)
        total_rows += len(rows)

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
            "rows_ingested": len(rows),
        }
        artifacts.append(write_artifact(f"pipelines/ingestion/ingest_{name}.json", json.dumps(pipeline, indent=2)))
        artifacts.append(write_json_artifact(f"bronze/{name}.json", rows))
        findings.append({
            "title": f"ingest_{name}",
            "detail": f"{pipeline['load_type']} → {pipeline['target']} (cron {pipeline['schedule_cron']}, "
                      f"{len(rows)} rows landed, {len(pipeline['dq_gates'])} DQ gates)",
        })

        system_node = f"src_{name}"
        bronze_node = f"bronze_{name}"
        ctx.add_node(system_node, f"Source: {name}", "source-system")
        ctx.add_node(bronze_node, f"bronze.{name} ({len(rows)} rows)", "bronze")
        ctx.add_edge(system_node, bronze_node, "ingest")

    status = "FAILURE" if landing_errors else "SUCCESS"
    ctx.audit("ingestion-agent", "pipeline-generation", status,
              f"generated {len(source_objects)} bronze pipelines, landed {total_rows} rows"
              if not landing_errors else "; ".join(landing_errors))

    result = AgentResult(
        agent="ingestion-agent",
        status=status,
        summary=(f"Generated {len(source_objects)} bronze ingestion pipelines and landed {total_rows} rows"
                 if not landing_errors else f"Ingestion failed: {'; '.join(landing_errors)}"),
        findings=findings,
        artifacts=artifacts,
    )
    print_report(result)
    return ctx.record(result)


if __name__ == "__main__":
    run(PipelineContext())
