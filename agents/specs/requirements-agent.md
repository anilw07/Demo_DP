# Data Product Requirements Agent

**Purpose** — Author and validate the data product requirement definition as an **ODPS v4.1** document (`data-product/customer-360.odps.yaml`): strategy and KPIs, identity, SLA and data-quality objectives, output ports, license and data holder.

**Trigger** — After the discovery agent recommends *build new* (or *extend*).

**Inputs**
- Business brief from the product owner
- Discovery report (`output/discovery/discovery_report.json`)
- ODPS v4.1 schema (`https://opendataproducts.org/v4.1/schema/odps.yaml`)

**Outputs**
- Validated ODPS document (mock validates the checked-in definition)
- `output/requirements/odps_validation.json` — validation result + requirements summary
- Audit event (`odps-validation`)

**Mock behaviour** — Loads the ODPS YAML, asserts required root fields (`schema`, `version`, `product`), required identity fields (`name`, `productID`, `visibility`, `status`, `type`) and the ODCS contract link, then summarises strategy, ports and KPIs.

**Production tools** — LLM drafting from the business brief, JSON-Schema validation against the published ODPS schema, review workflow with the data product owner, versioned publication to the product registry.

**Guardrails**
- Document must link a data contract (`product.contract.type: ODCS`) before it can leave `draft` status.
- KPIs must be measurable (unit + target + calculation).
