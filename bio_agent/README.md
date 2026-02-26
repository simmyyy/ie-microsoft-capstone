# Biodiversity Risk Analysis Agent

Production-ready AWS Bedrock Agent for analyzing biodiversity risk/impact for H3 cells. Includes Lambda tools, tool definitions, and agent instructions.

## Structure

```
bio_agent/
├── lambda_handler.py          # Main Lambda entry (routes by apiPath/function)
├── db.py                      # PostgreSQL connection (env + Secrets Manager)
├── tools/
│   ├── validation.py         # Input validation
│   ├── get_hex_metrics.py
│   ├── get_neighbor_hexes.py
│   ├── get_neighbor_summary.py
│   ├── get_hex_species_context.py
│   ├── get_osm_context.py
│   ├── get_info_about_threatened_species.py
│   └── get_species_profiles.py
├── tool_definitions.json      # OpenAPI 3.0 schema for Bedrock Action Group
├── tool_definitions_function_schema.json  # Function-details format
├── agent_instructions.md      # System prompt for the agent
├── requirements.txt
└── README.md
```

## Database Configuration

### Option 1: Environment variables
```
PGHOST=your-db.cluster-xxx.region.rds.amazonaws.com
PGPORT=5432
PGDATABASE=postgres
PGUSER=postgres
PGPASSWORD=secret
PG_SCHEMA=serving   # or biodiversity_db – must match your gold tables
```

### Option 2: Secrets Manager
Store a secret (e.g. `rds!cluster-xxx`) with JSON:
```json
{
  "host": "your-db.cluster-xxx.region.rds.amazonaws.com",
  "port": 5432,
  "dbname": "postgres",
  "username": "postgres",
  "password": "secret"
}
```
Set `SECRET_ARN` to the secret ARN.

## Required Tables (schema: `serving` or `biodiversity_db`)

- `gbif_cell_metrics` – h3_index, h3_resolution, country, year, observation_count, species_richness_cell, n_threatened_species, threat_score_weighted, dqi, shannon_h, simpson_1_minus_d
- `gbif_species_dim` – taxon_key, species_name, occurrence_count, is_threatened, is_invasive, country, year
- `gbif_species_h3_mapping` – h3_index, taxon_key, occurrence_count, is_threatened, is_invasive, h3_resolution, country, year
- `iucn_species_profiles` – scientific_name, iucn_category, rationale, habitat_ecology, population, threats_text, conservation_text, population_trend
- `osm_hex_features` – h3_index, h3_resolution, country, road_count, major_road_count, protected_area_pct, etc.

## Deployment (Lambda)

1. Install dependencies:
   ```bash
   cd bio_agent && pip install -r requirements.txt -t .
   ```

2. Zip the package:
   ```bash
   zip -r bio_agent.zip lambda_handler.py db.py tools/
   ```

3. Create Lambda function (or use SAM/CloudFormation):
   - Handler: `lambda_handler.lambda_handler`
   - Runtime: Python 3.11+
   - Environment: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD (or SECRET_ARN)
   - Optional: PG_SCHEMA (default: `serving`)

4. Attach resource-based policy for Bedrock:
   ```json
   {
     "Effect": "Allow",
     "Principal": { "Service": "bedrock.amazonaws.com" },
     "Action": "lambda:InvokeFunction",
     "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:FUNCTION_NAME",
     "Condition": {
       "ArnLike": { "AWS:SourceArn": "arn:aws:bedrock:REGION:ACCOUNT:agent/*" }
     }
   }
   ```

## Bedrock Agent Setup

1. Create an agent in Amazon Bedrock.
2. Add an Action Group with Lambda:
   - Use `tool_definitions.json` (OpenAPI) or define functions from `tool_definitions_function_schema.json`.
   - Attach the Lambda function.
3. Set the agent instructions from `agent_instructions.md` in the system prompt.

## Tools

| Tool | Purpose |
|------|---------|
| GetHexMetrics | Metrics for a single H3 cell + trend |
| GetNeighborHexes | k-ring neighbors + neighbor_set_id |
| GetNeighborSummary | Aggregated stats for neighbor cells |
| GetHexSpeciesContext | Top species, threatened, invasive |
| GetOSMContext | Roads, ports, airports, protected areas |
| GetInfoAboutThreatenedSpecies | IUCN info for threatened species |
| GetSpeciesProfiles | Profile text for species (narrative) |

## Local Testing

```python
# Simulate Bedrock event (OpenAPI)
event = {
    "messageVersion": "1.0",
    "actionGroup": "BiodiversityTools",
    "apiPath": "/getHexMetrics",
    "httpMethod": "POST",
    "parameters": [],
    "requestBody": {
        "content": {
            "application/json": {
                "properties": [
                    {"name": "h3_id", "type": "string", "value": "861f1a47fffffff"},
                    {"name": "h3_res", "type": "integer", "value": "8"}
                ]
            }
        }
    }
}
# Run: lambda_handler.lambda_handler(event, None)
```
