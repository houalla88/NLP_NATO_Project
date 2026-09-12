"""Couche de mesure : formules pures, sans I/O, sans etat global."""

from .contestedness import detect_identity_reverts, ewma, mutual_revert_index, profile
from .distinctive import detect_silences, distinctive_concepts, fightin_words
from .distributions import (
    DEFAULT_SECTION_WEIGHTS,
    SmoothingPolicy,
    background_counts,
    build_all,
    build_distribution,
    concept_space,
    weighted_counts,
)
from .divergence import (
    UncertaintyConfig,
    bootstrap_interval,
    divergence_matrix,
    hellinger,
    jensen_shannon,
    jensen_shannon_corrected,
    overlap,
    permutation_p_value,
)
from .drift import drift_series
from .embedding import classical_mds, embed_divergence

__all__ = [
    "DEFAULT_SECTION_WEIGHTS", "SmoothingPolicy", "UncertaintyConfig",
    "background_counts", "bootstrap_interval", "build_all", "build_distribution",
    "classical_mds", "concept_space", "detect_identity_reverts", "detect_silences",
    "distinctive_concepts", "divergence_matrix", "drift_series", "embed_divergence",
    "ewma", "fightin_words", "hellinger", "jensen_shannon", "jensen_shannon_corrected", "mutual_revert_index",
    "overlap", "permutation_p_value", "profile", "weighted_counts",
]
