"""Couche domaine : structures de donnees et invariants, sans I/O."""

from .errors import (
    ConfigurationError,
    CorpusError,
    InsufficientDataError,
    PrismeError,
    SourceError,
    SourceUnavailableError,
)
from .models import (
    AnalysisReport,
    ArticleSnapshot,
    ConceptDistribution,
    ConceptObservation,
    ContestednessProfile,
    DistinctiveConcept,
    DivergenceMatrix,
    DivergencePair,
    DriftPoint,
    EntityDossier,
    Interval,
    Provenance,
    RevisionRecord,
    SilenceFinding,
    canonical_hash,
    to_jsonable,
    utcnow,
    validate_lang,
    validate_qid,
)

__all__ = [
    "AnalysisReport", "ArticleSnapshot", "ConceptDistribution", "ConceptObservation",
    "ContestednessProfile", "ConfigurationError", "CorpusError", "DistinctiveConcept",
    "DivergenceMatrix", "DivergencePair", "DriftPoint", "EntityDossier",
    "InsufficientDataError", "Interval", "PrismeError", "Provenance", "RevisionRecord",
    "SilenceFinding", "SourceError", "SourceUnavailableError", "canonical_hash",
    "to_jsonable", "utcnow", "validate_lang", "validate_qid",
]
