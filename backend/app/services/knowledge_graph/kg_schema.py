"""
Knowledge graph dataclasses and ontology / edge-type constants.

These are the in-memory structures used by the repository, the seed scripts,
and the API router. They are intentionally light-weight (no external
validation library) to keep the graph layer dependency-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# Ontology vocabulary
#   Must stay in sync with the ENUM in
#   database/migrations/add_knowledge_graph.sql.
# ---------------------------------------------------------------------------

ONTOLOGIES: tuple[str, ...] = (
    "umls",
    "snomed",
    "icd10",
    "hcc",
    "atc",
    "rxnorm",
    "loinc",
    "custom",
)


# ---------------------------------------------------------------------------
# Edge type vocabulary
#   The DB column is VARCHAR(64), so downstream agents can extend this list.
#   These constants are simply the canonical set used by the bootstrap seed
#   so all early consumers agree on spelling.
# ---------------------------------------------------------------------------


class EdgeType:
    """Canonical edge type names — use these instead of magic strings."""

    MAPS_TO = "maps_to"                    # cross-ontology equivalence (icd10 -> hcc)
    SUBCLASS_OF = "subclass_of"            # hierarchical is-a
    HAS_INDICATION = "has_indication"      # drug -> condition it treats
    TREATED_BY = "treated_by"              # condition -> drug class
    HAS_COMPLICATION = "has_complication"  # condition -> downstream condition
    COMORBID_WITH = "comorbid_with"        # condition <-> condition co-occurrence
    HAS_LAB_SIGNAL = "has_lab_signal"      # condition -> diagnostic lab (LOINC)
    CONTRAINDICATED_WITH = "contraindicated_with"
    PART_OF = "part_of"


EDGE_TYPES: tuple[str, ...] = tuple(
    v for k, v in vars(EdgeType).items() if not k.startswith("_") and isinstance(v, str)
)


# ---------------------------------------------------------------------------
# Concept
# ---------------------------------------------------------------------------


@dataclass
class Concept:
    """A node in the knowledge graph."""

    ontology: str
    code: str
    preferred_label: str
    concept_uri: str | None = None       # auto-derived as f"{ontology}:{code}" when missing
    definition: str | None = None
    semantic_type: str | None = None
    is_active: bool = True
    metadata: dict[str, Any] | None = None
    id: int | None = None
    created_at: Any | None = None
    updated_at: Any | None = None

    def __post_init__(self) -> None:
        if self.ontology not in ONTOLOGIES:
            raise ValueError(
                f"Unknown ontology {self.ontology!r}; must be one of {ONTOLOGIES}"
            )
        if not self.code:
            raise ValueError("Concept.code must be non-empty")
        if not self.preferred_label:
            raise ValueError("Concept.preferred_label must be non-empty")
        if self.concept_uri is None:
            self.concept_uri = f"{self.ontology}:{self.code}"


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------


@dataclass
class Edge:
    """A typed directed edge between two concepts."""

    src_concept_id: int
    dst_concept_id: int
    edge_type: str
    weight: float = 1.0
    source: str | None = None
    evidence_url: str | None = None
    metadata: dict[str, Any] | None = None
    id: int | None = None
    created_at: Any | None = None

    def __post_init__(self) -> None:
        if not self.edge_type:
            raise ValueError("Edge.edge_type must be non-empty")
        if len(self.edge_type) > 64:
            raise ValueError("Edge.edge_type is limited to 64 chars")
        if self.src_concept_id == self.dst_concept_id:
            raise ValueError("Edge.src_concept_id must differ from dst_concept_id")
        # Coerce Decimal -> float so callers that read from MySQL still work.
        if isinstance(self.weight, Decimal):
            self.weight = float(self.weight)
        if not 0.0 <= float(self.weight) <= 1.0:
            raise ValueError(f"Edge.weight {self.weight!r} must be in [0.0, 1.0]")
