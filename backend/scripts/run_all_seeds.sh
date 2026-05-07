#!/bin/sh
# Run every Knowledge-Graph seed script in dependency order.
#
# Designed to run inside the raf-backend container::
#
#     docker exec raf-backend sh /app/scripts/run_all_seeds.sh
#
# Or, on the host (after `pip install -r backend/requirements.txt`)::
#
#     PYTHONPATH=$(pwd)/backend sh backend/scripts/run_all_seeds.sh
#
# Each seed is idempotent — re-running upserts, never duplicates.  Seeds
# require migrations to have been applied first (run apply_migrations.py
# before this script).
#
# Order matters:
#   1. snomed concepts  → must exist before evidence_rules / atc bridges
#   2. loinc            → optional but cheap; ICD-10 / HCC links
#   3. atc              → drug class hierarchy + RxNorm bridges
#   4. brand→generic    → depends on atc
#   5. comorbidity      → depends on knowledge_graph_concepts (via HCC)
#   6. demographic      → standalone
#   7. specialty priors → depends on knowledge_graph_concepts
#   8. evidence rules   → depends on knowledge_graph_concepts (HCC + ICD-10)

set -e

SCRIPTS_DIR="$(dirname "$0")"
cd "$SCRIPTS_DIR/.." || exit 1
export PYTHONPATH="${PYTHONPATH:-/app}"

run() {
  printf '  %-40s ... ' "$1"
  if python "$SCRIPTS_DIR/$1" >/tmp/seed.log 2>&1; then
    tail -1 /tmp/seed.log | sed 's/^.*INFO[^:]*: */OK /' | sed 's/^/     /'
  else
    echo "FAIL — see /tmp/seed.log"
    cat /tmp/seed.log
    exit 1
  fi
}

echo "Running KG seeds (PYTHONPATH=$PYTHONPATH)..."
run seed_snomed_top_concepts.py
run seed_loinc_top_signals.py
run seed_atc_top_classes.py
run seed_brand_to_generic.py
run seed_comorbidity_patterns.py
run seed_demographic_risk_factors.py
run seed_specialty_hcc_priors.py
run seed_kg_evidence_rules.py
echo "All seeds applied."
