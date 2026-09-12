"""Orchestration : d'un dossier d'entite a un rapport auditable.

Cette couche ne contient aucune formule. Elle enchaine les mesures, collecte
les avertissements, et scelle le resultat avec l'empreinte des donnees d'entree
et les parametres effectifs. Deux executions sur le meme corpus avec les memes
parametres produisent des chiffres identiques au bit pres - toutes les sources
d'alea sont sous graine fixe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .. import METHOD_VERSION
from ..domain.errors import InsufficientDataError
from ..domain.models import (
    AnalysisReport,
    ArticleSnapshot,
    EntityDossier,
    utcnow,
)
from ..metrics.contestedness import DEFAULT_BUCKET_DAYS, DEFAULT_LAMBDA, profile
from ..metrics.distinctive import (
    DEFAULT_PRIOR_STRENGTH,
    DEFAULT_Z_THRESHOLD,
    detect_silences,
    distinctive_concepts,
)
from ..metrics.distributions import (
    SmoothingPolicy,
    background_counts,
    build_all,
    weighted_counts,
)
from ..metrics.divergence import UncertaintyConfig, divergence_matrix
from ..metrics.drift import drift_series
from ..metrics.embedding import embed_divergence

# En deca de cette qualite d'ajustement, la carte en deux dimensions suggere
# des proximites que la matrice ne porte pas. Le rapport la marque alors comme
# non fiable plutot que de la retirer : la cacher priverait le lecteur de
# l'information que la structure n'est pas planaire.
MIN_EMBEDDING_FIT = 0.60


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    """Parametres effectifs d'une analyse. Integralement trace dans le rapport."""

    smoothing: SmoothingPolicy = field(default_factory=SmoothingPolicy)
    uncertainty: UncertaintyConfig = field(default_factory=UncertaintyConfig)
    section_weights: Mapping[str, float] | None = None
    prior_strength: float = DEFAULT_PRIOR_STRENGTH
    z_threshold: float = DEFAULT_Z_THRESHOLD
    top_distinctive_per_lang: int = 15
    silence_min_share: float = 0.005
    silence_min_editions: int = 2
    ewma_lambda: float = DEFAULT_LAMBDA
    bucket_days: int = DEFAULT_BUCKET_DAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "method_version": METHOD_VERSION,
            "smoothing": {
                "kind": self.smoothing.kind,
                "alpha": self.smoothing.alpha,
                "strength": self.smoothing.strength,
            },
            "uncertainty": {
                "bootstrap": self.uncertainty.bootstrap,
                "permutations": self.uncertainty.permutations,
                "level": self.uncertainty.level,
                "seed": self.uncertainty.seed,
            },
            "section_weights": dict(self.section_weights) if self.section_weights else "default",
            "prior_strength": self.prior_strength,
            "z_threshold": self.z_threshold,
            "top_distinctive_per_lang": self.top_distinctive_per_lang,
            "silence_min_share": self.silence_min_share,
            "silence_min_editions": self.silence_min_editions,
            "ewma_lambda": self.ewma_lambda,
            "bucket_days": self.bucket_days,
        }


def _data_nature(dossier: EntityDossier) -> str:
    """Nature des donnees, deduite de la provenance des instantanes.

    Remonte dans le rapport et dans l'interface. Un rapport dont la nature est
    synthetique ne doit jamais etre lu comme une observation sur le monde.
    """
    sources = {s.provenance.source_id for s in dossier.snapshots}
    if any("synthetic" in source for source in sources):
        return "synthetique"
    if any(source.startswith("mediawiki") for source in sources):
        return "empirique"
    if any(source.startswith("local:recorded") for source in sources):
        return "empirique-rejoue"
    return "indetermine"


def analyse(
    dossier: EntityDossier,
    config: AnalysisConfig | None = None,
    history: Mapping[str, Sequence[ArticleSnapshot]] | None = None,
    requested_langs: Sequence[str] | None = None,
) -> AnalysisReport:
    """Produit le rapport complet d'un dossier d'entite."""
    settings = config or AnalysisConfig()

    if len(dossier.snapshots) < 2:
        raise InsufficientDataError(
            "au moins deux editions sont necessaires : une divergence se mesure "
            "entre deux descriptions, pas sur une seule."
        )

    distributions, space, warnings = build_all(
        dossier, settings.smoothing, settings.section_weights
    )

    # Couverture demandee contre couverture obtenue : une edition absente est
    # signalee, jamais escamotee. Une comparaison silencieusement amputee d'une
    # edition est une comparaison biaisee.
    if requested_langs:
        missing = sorted(set(requested_langs) - set(dossier.langs))
        if missing:
            warnings.append(
                f"editions demandees mais absentes du corpus : {', '.join(missing)}. "
                "Les divergences portent uniquement sur les editions obtenues."
            )

    per_lang_counts = {
        s.lang: weighted_counts(s, settings.section_weights) for s in dossier.snapshots
    }
    background = background_counts(dossier, settings.section_weights)

    matrix = divergence_matrix(distributions, space, settings.uncertainty)

    non_significant = [
        f"{p.lang_a}/{p.lang_b}" for p in matrix.pairs if not p.is_significant
    ]
    if non_significant:
        warnings.append(
            "paires dont la divergence n'excede pas le bruit d'echantillonnage "
            f"(p >= 0.05) : {', '.join(non_significant)}. A ne pas interpreter."
        )

    distinctive = distinctive_concepts(
        per_lang_counts,
        background,
        dossier,
        prior_strength=settings.prior_strength,
        z_threshold=settings.z_threshold,
        top_per_lang=settings.top_distinctive_per_lang,
    )
    silences = detect_silences(
        per_lang_counts,
        dossier,
        min_share_elsewhere=settings.silence_min_share,
        min_editions_present=settings.silence_min_editions,
    )

    profiles = tuple(
        profile(s.lang, s.revisions, settings.ewma_lambda, settings.bucket_days)
        for s in dossier.snapshots
    )
    if all(p.n_revisions == 0 for p in profiles):
        warnings.append(
            "aucun historique de revision dans le corpus : les indicateurs de "
            "contestation sont nuls par absence de donnee, pas par absence de conflit."
        )

    drift: list = []
    for lang, snapshots in (history or {}).items():
        try:
            drift.extend(
                drift_series(lang, dossier.by_lang(lang), snapshots, settings.section_weights)
            )
        except KeyError:
            warnings.append(f"historique fourni pour {lang}, absent du dossier courant.")

    embedding, fit = embed_divergence(matrix.as_grid(), matrix.langs)
    if fit < MIN_EMBEDDING_FIT:
        warnings.append(
            f"qualite d'ajustement de la carte 2D faible ({fit:.0%}) : la structure "
            "des divergences n'est pas planaire, se referer a la matrice complete."
        )

    parameters = settings.as_dict()
    parameters["embedding_fit"] = fit
    parameters["concept_space_size"] = len(space)
    parameters["corpus_fingerprint"] = dossier.audit_fingerprint()

    return AnalysisReport(
        entity_qid=dossier.entity_qid,
        entity_label=dossier.label,
        corpus_id=dossier.corpus_id,
        method_version=METHOD_VERSION,
        generated_at=utcnow(),
        langs=matrix.langs,
        distributions=distributions,
        divergence=matrix,
        distinctive=distinctive,
        silences=silences,
        contestedness=profiles,
        drift=tuple(drift),
        embedding=embedding,
        parameters=parameters,
        input_fingerprint=dossier.audit_fingerprint(),
        warnings=tuple(warnings),
        data_nature=_data_nature(dossier),
    )
