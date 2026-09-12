"""Construction des distributions conceptuelles.

Passage de « une liste d'occurrences de concepts » a « une distribution de
probabilite sur l'espace conceptuel commun ». Toute la comparabilite
inter-langues repose sur le fait que cet espace est indexe par des QID
Wikidata, donc neutre linguistiquement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ..domain.errors import ConfigurationError, InsufficientDataError
from ..domain.models import (
    ArticleSnapshot,
    ConceptDistribution,
    EntityDossier,
)

# Ponderation structurelle par defaut.
#
# Hypothese : la position d'un concept dans un article porte de l'information
# de cadrage. Le chapeau introductif est ce que lit la majorite du trafic et
# ce que reprennent les moteurs de recherche et les assistants ; un concept
# qui y figure pese davantage dans la perception que le meme concept relegue
# en bibliographie.
#
# Ces coefficients sont une HYPOTHESE de modelisation, pas une mesure. Ils
# sont exposes en parametre precisement pour qu'une analyse de sensibilite
# puisse etre conduite dessus (cf. `docs/METHOD.md`, section « Limites »).
DEFAULT_SECTION_WEIGHTS: Mapping[str, float] = {
    "lead": 2.5,
    "body": 1.0,
    "infobox": 1.8,
    "criticism": 1.0,
    "seealso": 0.3,
    "references": 0.1,
    "": 1.0,
}

# En deca de ce nombre d'occurrences, une distribution n'est pas assez
# alimentee pour qu'une divergence soit interpretable : la variance
# d'echantillonnage domine le signal.
MIN_OBSERVATIONS = 25


@dataclass(frozen=True, slots=True)
class SmoothingPolicy:
    """Politique de lissage des distributions.

    Le lissage n'est pas cosmetique : la divergence de Kullback-Leibler est
    infinie des qu'un concept a une probabilite nulle dans une distribution et
    non nulle dans l'autre. La JSD, elle, reste finie sans lissage - c'est
    l'une des raisons de la preferer. Le lissage sert ici a un autre objectif :
    eviter qu'un concept vu une seule fois pese autant qu'un concept structurel
    dans les petits corpus.

    - `none`      : frequences brutes. Defaut, aucun parametre libre.
    - `laplace`   : +alpha sur chaque concept de l'espace commun.
    - `dirichlet` : prior proportionnel a la distribution de fond (tous corpus
                    confondus), d'intensite `strength` occurrences virtuelles.
    """

    kind: str = "none"
    alpha: float = 0.5
    strength: float = 10.0

    def __post_init__(self) -> None:
        if self.kind not in {"none", "laplace", "dirichlet"}:
            raise ConfigurationError(f"lissage inconnu : {self.kind!r}")
        if self.alpha < 0 or self.strength < 0:
            raise ConfigurationError("parametres de lissage negatifs")


def concept_space(dossier: EntityDossier) -> tuple[str, ...]:
    """Espace conceptuel commun : union triee des QID vus dans le dossier.

    Le tri garantit que deux executions produisent le meme ordre de colonnes,
    donc les memes resultats au bit pres.
    """
    qids: set[str] = set()
    for snapshot in dossier.snapshots:
        qids.update(c.qid for c in snapshot.concepts)
    return tuple(sorted(qids))


def weighted_counts(
    snapshot: ArticleSnapshot,
    section_weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Masse d'attention par concept, ponderee par la position structurelle.

    Une occurrence dont la section est inconnue recoit le poids neutre 1.0
    plutot que d'etre ecartee : un corpus incomplet doit degrader la precision,
    jamais introduire un biais de selection silencieux.
    """
    weights = dict(DEFAULT_SECTION_WEIGHTS if section_weights is None else section_weights)
    neutral = weights.get("", 1.0)
    accumulated: dict[str, float] = {}
    for observation in snapshot.concepts:
        structural = weights.get(observation.section, neutral)
        accumulated[observation.qid] = (
            accumulated.get(observation.qid, 0.0)
            + observation.count * observation.weight * structural
        )
    return accumulated


def background_counts(
    dossier: EntityDossier,
    section_weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Distribution de fond : toutes editions confondues.

    Sert de prior informatif pour la methode log-odds et de reference pour le
    lissage de Dirichlet.
    """
    pooled: dict[str, float] = {}
    for snapshot in dossier.snapshots:
        for qid, mass in weighted_counts(snapshot, section_weights).items():
            pooled[qid] = pooled.get(qid, 0.0) + mass
    return pooled


def build_distribution(
    snapshot: ArticleSnapshot,
    space: Sequence[str],
    smoothing: SmoothingPolicy | None = None,
    background: Mapping[str, float] | None = None,
    section_weights: Mapping[str, float] | None = None,
) -> ConceptDistribution:
    """Construit la distribution normalisee d'un instantane sur `space`."""
    policy = smoothing or SmoothingPolicy()
    counts = weighted_counts(snapshot, section_weights)
    observed_total = sum(counts.values())

    if observed_total <= 0:
        raise InsufficientDataError(
            f"{snapshot.lang}: aucune occurrence de concept exploitable"
        )

    smoothed: dict[str, float] = {}
    if policy.kind == "none":
        smoothed = {qid: counts.get(qid, 0.0) for qid in space}
    elif policy.kind == "laplace":
        smoothed = {qid: counts.get(qid, 0.0) + policy.alpha for qid in space}
    else:  # dirichlet
        if not background:
            raise ConfigurationError(
                "lissage 'dirichlet' demande sans distribution de fond"
            )
        background_total = sum(background.values()) or 1.0
        smoothed = {
            qid: counts.get(qid, 0.0)
            + policy.strength * (background.get(qid, 0.0) / background_total)
            for qid in space
        }

    total = sum(smoothed.values())
    if total <= 0:
        raise InsufficientDataError(f"{snapshot.lang}: masse totale nulle apres lissage")

    return ConceptDistribution(
        lang=snapshot.lang,
        probabilities={qid: mass / total for qid, mass in smoothed.items()},
        raw_counts=counts,
        total_mass=observed_total,
        smoothing=policy.kind,
    )


def build_all(
    dossier: EntityDossier,
    smoothing: SmoothingPolicy | None = None,
    section_weights: Mapping[str, float] | None = None,
) -> tuple[tuple[ConceptDistribution, ...], tuple[str, ...], list[str]]:
    """Construit toutes les distributions du dossier sur l'espace commun.

    Renvoie egalement les avertissements : une edition sous le seuil
    d'observations reste analysee, mais le rapport doit porter la mention.
    Ecarter silencieusement une edition trop courte reviendrait a choisir
    l'echantillon en fonction du resultat.
    """
    space = concept_space(dossier)
    if not space:
        raise InsufficientDataError("dossier vide : aucun concept observe")

    background = background_counts(dossier, section_weights)
    warnings: list[str] = []
    distributions: list[ConceptDistribution] = []

    for snapshot in dossier.snapshots:
        distribution = build_distribution(
            snapshot, space, smoothing, background, section_weights
        )
        if distribution.total_mass < MIN_OBSERVATIONS:
            warnings.append(
                f"{snapshot.lang}: {distribution.total_mass:.0f} occurrences ponderees "
                f"(< {MIN_OBSERVATIONS}) - divergences a lire avec leur intervalle, "
                "la variance d'echantillonnage domine."
            )
        distributions.append(distribution)

    return tuple(distributions), space, warnings
