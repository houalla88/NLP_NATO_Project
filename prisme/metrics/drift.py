"""Derive temporelle du cadrage, au sein d'une meme edition.

L'interet de Wikipedia comme terrain de mesure tient a son historique complet :
chaque revision est adressable par son identifiant et son horodatage. Il devient
possible de reconstruire la distribution conceptuelle d'un article a une date
passee et de la comparer a son etat de reference.

La mesure repond a « de combien cette edition s'est-elle eloignee d'elle-meme »,
et non a « qui a raison ». Une derive forte peut refleter l'actualisation
legitime d'un article apres un evenement majeur autant qu'une reecriture
orientee : la mesure localise le moment, elle ne qualifie pas l'intention.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from ..domain.models import ArticleSnapshot, DriftPoint
from .distributions import weighted_counts
from .divergence import jensen_shannon


def drift_series(
    lang: str,
    baseline: ArticleSnapshot,
    historical: Sequence[ArticleSnapshot],
    section_weights: Mapping[str, float] | None = None,
) -> list[DriftPoint]:
    """Distance de chaque etat historique a l'etat de reference.

    L'espace conceptuel est recalcule sur l'union du couple compare, et non sur
    l'union globale : comparer deux etats du meme article sur un espace nourri
    par d'autres langues introduirait des zeros communs qui tireraient
    mecaniquement la divergence vers le bas.
    """
    baseline_counts = weighted_counts(baseline, section_weights)
    points: list[DriftPoint] = []

    for snapshot in sorted(historical, key=lambda s: s.revision_timestamp):
        counts = weighted_counts(snapshot, section_weights)
        space = sorted(set(baseline_counts) | set(counts))
        if not space:
            continue

        baseline_total = sum(baseline_counts.values()) or 1.0
        current_total = sum(counts.values()) or 1.0
        p = [baseline_counts.get(qid, 0.0) / baseline_total for qid in space]
        q = [counts.get(qid, 0.0) / current_total for qid in space]

        points.append(
            DriftPoint(
                lang=lang,
                at=snapshot.revision_timestamp,
                revision_id=snapshot.revision_id,
                jsd_vs_baseline=jensen_shannon(p, q),
                support=len([qid for qid in space if counts.get(qid, 0.0) > 0]),
            )
        )

    return points
