"""Contestation editoriale : mesurer la stabilite d'un texte, pas sa veracite.

Un article dont la formulation est constamment defaite et refaite par ses
contributeurs porte une information que le texte final ne porte pas : le
consensus n'est pas atteint. Cette instabilite est mesurable sans lire une
seule ligne, a partir des seules metadonnees de revision.

Detection des retours arriere
-----------------------------
MediaWiki expose pour chaque revision l'empreinte SHA-1 de son contenu. Si une
revision reproduit exactement l'empreinte d'une revision anterieure, l'etat du
texte a ete restaure a l'identique : c'est la definition operationnelle du
« revert d'identite » utilisee dans la litterature (Sumi et al., 2011 ; Yasseri
et al., 2012, « Dynamics of Conflicts in Wikipedia », PLoS ONE 7(6)).

Cette definition est volontairement stricte. Elle rate les annulations
partielles et les reformulations qui suppriment le meme contenu sans restaurer
le texte au caractere pres. Elle ne produit en revanche presque aucun faux
positif, ce qui en fait un plancher fiable : un taux de revert mesure ainsi
sous-estime le conflit, il ne l'invente pas.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from ..domain.models import ContestednessProfile, RevisionRecord

# Facteur de lissage exponentiel de l'intensite d'edition. 0.94 est la valeur
# RiskMetrics pour la volatilite quotidienne ; elle est reprise ici pour sa
# demi-vie (environ 11 pas) et non par analogie theorique - il n'y a pas de
# modele de rendement derriere une serie d'edition. Voir la mise en garde en
# fin de module.
DEFAULT_LAMBDA = 0.94

# Granularite de la serie d'intensite. 7 jours absorbe le cycle hebdomadaire
# de l'activite contributive sans ecraser les pics de quelques jours qui
# signalent un evenement exterieur.
DEFAULT_BUCKET_DAYS = 7


def detect_identity_reverts(
    revisions: Sequence[RevisionRecord],
) -> list[tuple[int, list[int]]]:
    """Retours arriere par identite de contenu.

    Renvoie une liste de (index de la revision restauratrice, index des
    revisions ainsi defaites). Les revisions defaites sont celles situees
    strictement entre l'etat restaure et la restauration.

    Le cas `distance == 1` est exclu : une revision identique a son parent
    immediat ne defait rien (edition nulle, sauvegarde a vide).
    """
    last_seen: dict[str, int] = {}
    reverts: list[tuple[int, list[int]]] = []

    for index, revision in enumerate(revisions):
        digest = revision.sha1
        if not digest:
            continue
        previous = last_seen.get(digest)
        if previous is not None and index - previous > 1:
            reverts.append((index, list(range(previous + 1, index))))
        last_seen[digest] = index

    return reverts


def mutual_revert_index(
    revisions: Sequence[RevisionRecord],
    reverts: Sequence[tuple[int, list[int]]],
) -> float:
    """Indice de conflit fonde sur les paires de contributeurs qui se defont.

    Adaptation de la mesure M de Yasseri et al. (2012). La formule implementee
    est explicitement :

        MRI = somme sur les paires {a, b} de  min(r_ab, r_ba) * max(N_a, N_b)

    ou r_ab est le nombre de fois ou a a defait b, et N_a le nombre total
    d'editions de a. Puis normalisation par le nombre de revisions.

    Lecture : seules les paires *mutuelles* comptent (min des deux sens), ce
    qui distingue un conflit d'une simple patrouille anti-vandalisme, ou le
    flux est a sens unique. Le facteur max(N_a, N_b) donne plus de poids aux
    affrontements entre contributeurs etablis qu'aux passages de comptes
    ephemeres.

    Ce n'est PAS la mesure M publiee au coefficient pres : Yasseri et al.
    ponderent en outre par le nombre d'editeurs et appliquent un traitement
    specifique aux paires dominantes. L'indice est donc comparable entre
    editions au sein d'une meme execution PRISME, mais ne doit pas etre
    confronte a des valeurs de M issues de la litterature.
    """
    edit_counts: dict[str, int] = defaultdict(int)
    for revision in revisions:
        if revision.editor:
            edit_counts[revision.editor] += 1

    reverted_by: dict[tuple[str, str], int] = defaultdict(int)
    for reverter_index, undone_indexes in reverts:
        reverter = revisions[reverter_index].editor
        if not reverter:
            continue
        for undone_index in undone_indexes:
            undone_editor = revisions[undone_index].editor
            if not undone_editor or undone_editor == reverter:
                continue
            reverted_by[(reverter, undone_editor)] += 1

    seen_pairs: set[tuple[str, str]] = set()
    total = 0.0
    for (a, b) in reverted_by:
        pair = (a, b) if a < b else (b, a)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        forward = reverted_by.get((pair[0], pair[1]), 0)
        backward = reverted_by.get((pair[1], pair[0]), 0)
        mutual = min(forward, backward)
        if mutual == 0:
            continue
        total += mutual * max(edit_counts[pair[0]], edit_counts[pair[1]])

    return total / len(revisions) if revisions else 0.0


def intensity_series(
    revisions: Sequence[RevisionRecord],
    bucket_days: int = DEFAULT_BUCKET_DAYS,
) -> list[tuple[datetime, float]]:
    """Nombre d'editions par fenetre, du plus ancien au plus recent."""
    if not revisions:
        return []
    ordered = sorted(revisions, key=lambda r: r.timestamp)
    start = ordered[0].timestamp
    span = timedelta(days=bucket_days)

    buckets: dict[int, int] = defaultdict(int)
    for revision in ordered:
        offset = int((revision.timestamp - start) / span)
        buckets[offset] += 1

    last_offset = max(buckets)
    # Les fenetres vides sont materialisees a zero : sans cela, une periode de
    # calme disparaitrait de la serie et l'EWMA surestimerait l'intensite.
    return [(start + span * i, float(buckets.get(i, 0))) for i in range(last_offset + 1)]


def ewma(series: Sequence[float], lam: float = DEFAULT_LAMBDA) -> float:
    """Moyenne exponentiellement ponderee, initialisee sur la premiere valeur."""
    if not series:
        return 0.0
    value = series[0]
    for observation in series[1:]:
        value = lam * value + (1.0 - lam) * observation
    return value


def profile(
    lang: str,
    revisions: Sequence[RevisionRecord],
    lam: float = DEFAULT_LAMBDA,
    bucket_days: int = DEFAULT_BUCKET_DAYS,
) -> ContestednessProfile:
    """Profil de contestation complet d'une edition."""
    ordered = sorted(revisions, key=lambda r: r.timestamp)
    count = len(ordered)

    if count == 0:
        return ContestednessProfile(
            lang=lang,
            n_revisions=0,
            window_days=0.0,
            identity_reverts=0,
            revert_rate=0.0,
            mutual_revert_index=0.0,
            distinct_editors=0,
            anonymous_share=0.0,
            ewma_intensity=0.0,
        )

    reverts = detect_identity_reverts(ordered)
    series = intensity_series(ordered, bucket_days)
    window = (ordered[-1].timestamp - ordered[0].timestamp).total_seconds() / 86400.0
    anonymous = sum(1 for r in ordered if r.is_anonymous)

    return ContestednessProfile(
        lang=lang,
        n_revisions=count,
        window_days=window,
        identity_reverts=len(reverts),
        revert_rate=len(reverts) / count,
        mutual_revert_index=mutual_revert_index(ordered, reverts),
        distinct_editors=len({r.editor for r in ordered if r.editor}),
        anonymous_share=anonymous / count,
        ewma_intensity=ewma([value for _, value in series], lam),
        intensity_series=tuple(series),
    )


# ---------------------------------------------------------------------------
# Mise en garde sur l'analogie financiere
# ---------------------------------------------------------------------------
#
# L'intensite d'edition lissee ressemble formellement a une volatilite
# realisee, et la tentation est forte de la traiter comme telle. Elle ne l'est
# pas, pour trois raisons qui doivent figurer dans toute note d'accompagnement
# d'un usage decisionnel :
#
# 1. Il n'y a pas de rendement sous-jacent. Une volatilite mesure la dispersion
#    d'une variation de prix ; ici on mesure une frequence d'evenements. Le
#    parallele est morphologique, pas theorique.
# 2. Le processus n'est pas stationnaire et l'echantillon est endogene :
#    l'attention mediatique cree simultanement l'evenement et son edition.
# 3. Aucune propriete de martingale n'est verifiee, donc aucune agregation
#    temporelle en racine du temps n'est justifiee.
#
# Ce qui reste legitime : l'usage en variable *ordinale* pour classer des
# entites entre elles a date donnee, et la detection de rupture de niveau.
# Ce qui ne l'est pas : l'injection directe dans un modele de risque calibre.
