"""Concepts distinctifs et silences.

Pourquoi pas une simple difference de frequences
------------------------------------------------
Classer les concepts par ecart de frequence entre deux editions fait remonter
en tete les concepts rares : un QID vu une seule fois dans une seule edition
obtient un ratio de frequences infini. Le classement mesure alors la taille de
l'echantillon, pas le cadrage.

La methode retenue est celle de Monroe, Colaresi & Quinn (2008), « Fightin'
Words: Lexical Feature Selection and Evaluation for Identifying the Content of
Political Conflict », Political Analysis 16(4). Elle applique un prior de
Dirichlet informatif construit sur la distribution de fond, puis divise le
log-odds par son ecart-type. Le resultat est un score z : un concept rare doit
etre tres deseequilibre pour atteindre le meme score qu'un concept frequent
moderement deseequilibre. C'est exactement le comportement recherche.

Transposition
-------------
Monroe et al. travaillent sur des mots ; on travaille sur des identifiants
Wikidata. La structure statistique est identique (comptages sur un vocabulaire
ferme, deux groupes a comparer), la transposition ne demande aucune adaptation
de la formule. Elle apporte en revanche un avantage : le « vocabulaire » est
deja desambiguise et neutre linguistiquement, ce qui evacue les questions de
lemmatisation et de traduction qui fragilisent l'approche lexicale classique.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from ..domain.models import DistinctiveConcept, EntityDossier, SilenceFinding

# Intensite du prior, en occurrences virtuelles reparties sur le vocabulaire
# selon la distribution de fond. Valeur usuelle chez Monroe et al. Elle agit
# comme un regulateur : plus elle est elevee, plus il faut de preuve pour
# qu'un concept rare remonte dans le classement.
DEFAULT_PRIOR_STRENGTH = 500.0

# Un score z de 1.96 correspond au seuil bilateral a 5 % sous approximation
# normale. Retenu comme plancher d'affichage par defaut : en dessous, l'ecart
# n'est pas distinguable du bruit de comptage.
DEFAULT_Z_THRESHOLD = 1.96


def fightin_words(
    counts_in: Mapping[str, float],
    counts_out: Mapping[str, float],
    background: Mapping[str, float],
    lang: str,
    labels: Mapping[str, str] | None = None,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> list[DistinctiveConcept]:
    """Score z de sur-representation d'un groupe contre l'autre.

    `counts_in`  : effectifs de l'edition analysee.
    `counts_out` : effectifs de toutes les autres editions cumulees.
    `background` : effectifs de reference servant a construire le prior.
    """
    label_map = labels or {}
    background_total = sum(background.values())
    if background_total <= 0:
        return []

    vocabulary = sorted(set(counts_in) | set(counts_out) | set(background))
    # alpha_w : masse de prior allouee au concept w.
    alpha = {
        qid: prior_strength * (background.get(qid, 0.0) / background_total)
        for qid in vocabulary
    }
    alpha_total = sum(alpha.values())

    n_in = sum(counts_in.values())
    n_out = sum(counts_out.values())
    if n_in <= 0 or n_out <= 0:
        return []

    share_total_in = n_in or 1.0
    share_total_out = n_out or 1.0

    results: list[DistinctiveConcept] = []
    for qid in vocabulary:
        a_w = alpha[qid]
        y_in = counts_in.get(qid, 0.0)
        y_out = counts_out.get(qid, 0.0)

        numerator_in = y_in + a_w
        numerator_out = y_out + a_w
        # Complements : masse restante du groupe, prior compris.
        denominator_in = n_in + alpha_total - numerator_in
        denominator_out = n_out + alpha_total - numerator_out
        if numerator_in <= 0 or numerator_out <= 0:
            continue
        if denominator_in <= 0 or denominator_out <= 0:
            continue

        log_odds = math.log(numerator_in / denominator_in) - math.log(
            numerator_out / denominator_out
        )
        # Variance approchee du log-odds (Monroe et al., eq. 20).
        variance = 1.0 / numerator_in + 1.0 / numerator_out
        if variance <= 0:
            continue
        z_score = log_odds / math.sqrt(variance)

        if abs(z_score) < z_threshold:
            continue

        results.append(
            DistinctiveConcept(
                qid=qid,
                label=label_map.get(qid, qid),
                lang=lang,
                z_score=z_score,
                log_odds=log_odds,
                count_in=y_in,
                count_out=y_out,
                share_in=y_in / share_total_in,
                share_out=y_out / share_total_out,
            )
        )

    results.sort(key=lambda d: abs(d.z_score), reverse=True)
    return results


def distinctive_concepts(
    per_lang_counts: Mapping[str, Mapping[str, float]],
    background: Mapping[str, float],
    dossier: EntityDossier,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    top_per_lang: int = 15,
) -> tuple[DistinctiveConcept, ...]:
    """Concepts distinctifs de chaque edition, contre toutes les autres."""
    labels = dict(dossier.concept_labels)
    collected: list[DistinctiveConcept] = []

    for lang, counts_in in per_lang_counts.items():
        counts_out: dict[str, float] = {}
        for other_lang, other_counts in per_lang_counts.items():
            if other_lang == lang:
                continue
            for qid, mass in other_counts.items():
                counts_out[qid] = counts_out.get(qid, 0.0) + mass

        scored = fightin_words(
            counts_in=counts_in,
            counts_out=counts_out,
            background=background,
            lang=lang,
            labels=labels,
            prior_strength=prior_strength,
            z_threshold=z_threshold,
        )
        collected.extend(scored[:top_per_lang])

    return tuple(collected)


def detect_silences(
    per_lang_counts: Mapping[str, Mapping[str, float]],
    dossier: EntityDossier,
    min_share_elsewhere: float = 0.005,
    min_editions_present: int = 2,
) -> tuple[SilenceFinding, ...]:
    """Concepts installes ailleurs et totalement absents d'une edition.

    Deux garde-fous evitent de transformer du hasard redactionnel en constat :
    le concept doit peser au moins `min_share_elsewhere` de l'attention la ou
    il est present, et etre present dans au moins `min_editions_present`
    editions. Un concept vu une fois dans une seule edition et absent des
    autres ne dit rien.

    Ce que la mesure ne dit pas : l'absence d'un lien interne n'est pas
    l'absence du sujet. Une edition peut traiter un theme en prose sans jamais
    le lier. Le silence mesure ici est un silence *structurel* - le theme n'est
    pas rattache au reseau de concepts - ce qui est un signal plus faible mais
    plus objectivable qu'une absence semantique.
    """
    langs = sorted(per_lang_counts)
    totals = {
        lang: sum(counts.values()) or 1.0 for lang, counts in per_lang_counts.items()
    }

    findings: list[SilenceFinding] = []
    all_qids = sorted({qid for counts in per_lang_counts.values() for qid in counts})

    for qid in all_qids:
        present_in = [
            lang
            for lang in langs
            if per_lang_counts[lang].get(qid, 0.0) / totals[lang] >= min_share_elsewhere
        ]
        if len(present_in) < min_editions_present:
            continue
        for lang in langs:
            if per_lang_counts[lang].get(qid, 0.0) > 0:
                continue
            shares = [per_lang_counts[l].get(qid, 0.0) / totals[l] for l in present_in]
            findings.append(
                SilenceFinding(
                    qid=qid,
                    label=dossier.label_for(qid),
                    absent_in=lang,
                    present_in=tuple(present_in),
                    mean_share_elsewhere=sum(shares) / len(shares),
                )
            )

    findings.sort(key=lambda f: f.mean_share_elsewhere, reverse=True)
    return tuple(findings)
