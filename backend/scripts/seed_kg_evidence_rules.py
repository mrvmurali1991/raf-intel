#!/usr/bin/env python3
"""seed_kg_evidence_rules.py

Idempotently seed the kg_evidence_rules table from the curated catalogue
defined in app.services.knowledge_graph.evidence_rules_engine.

Usage:
    python scripts/seed_kg_evidence_rules.py

Requires: backend env (DB_*) configured so app.db.raf_cursor() can connect.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make backend/ importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.db import raf_cursor  # noqa: E402
from app.services.knowledge_graph.evidence_rules_engine import CURATED_RULES  # noqa: E402


_INSERT_SQL = """
INSERT INTO kg_evidence_rules
    (rule_name, rule_description, trigger_logic, trigger_conditions,
     output_hcc, output_icd10, confidence, source_type, source_citation,
     source_url, source_year, model_version, is_active)
VALUES
    (%(rule_name)s, %(rule_description)s, %(trigger_logic)s,
     %(trigger_conditions)s, %(output_hcc)s, %(output_icd10)s,
     %(confidence)s, %(source_type)s, %(source_citation)s,
     %(source_url)s, %(source_year)s, %(model_version)s, %(is_active)s)
ON DUPLICATE KEY UPDATE
    rule_description=VALUES(rule_description),
    trigger_logic=VALUES(trigger_logic),
    trigger_conditions=VALUES(trigger_conditions),
    output_hcc=VALUES(output_hcc),
    output_icd10=VALUES(output_icd10),
    confidence=VALUES(confidence),
    source_type=VALUES(source_type),
    source_citation=VALUES(source_citation),
    source_url=VALUES(source_url),
    source_year=VALUES(source_year),
    model_version=VALUES(model_version),
    is_active=VALUES(is_active)
"""


def main() -> int:
    inserted = 0
    with raf_cursor() as cur:
        for rule in CURATED_RULES:
            params = {
                "rule_name": rule["rule_name"],
                "rule_description": rule.get("rule_description"),
                "trigger_logic": rule.get("trigger_logic", "all"),
                "trigger_conditions": json.dumps(rule["trigger_conditions"]),
                "output_hcc": str(rule["output_hcc"]),
                "output_icd10": rule.get("output_icd10"),
                "confidence": float(rule.get("confidence", 0.75)),
                "source_type": rule["source_type"],
                "source_citation": rule["source_citation"],
                "source_url": rule.get("source_url"),
                "source_year": rule.get("source_year"),
                "model_version": rule.get("model_version", "V28"),
                "is_active": int(rule.get("is_active", 1)),
            }
            cur.execute(_INSERT_SQL, params)
            inserted += 1
    print(f"Seeded/updated {inserted} evidence rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
