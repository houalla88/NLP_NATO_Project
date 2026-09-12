"""Scenario de demonstration.

AVERTISSEMENT QUI VAUT POUR TOUT CE MODULE
------------------------------------------
Les corpus produits ici sont ENTIEREMENT GENERES. Ils ne contiennent aucune
observation sur Wikipedia, sur l'OTAN, ni sur quoi que ce soit d'autre. Ils
servent a une seule chose : montrer a quoi ressemble une sortie de PRISME quand
les donnees existent.

Trois garde-fous rendent la confusion impossible :

1. Les identifiants de concepts appartiennent a la plage reservee Q9xxxxxxxx.
   Ils n'existent pas sur Wikidata ; toute tentative de les resoudre echoue.
2. Le corpus porte `nature: "synthetic-demo"`, valeur propagee jusque dans le
   rapport, l'export JSON, l'interface web et le rapport HTML, ou elle declenche
   un bandeau non masquable.
3. Les libellés sont thematiques et non factuels : ils rendent la sortie
   lisible, ils n'affirment rien.

Pourquoi une demonstration synthetique plutot qu'une collecte reelle : la
session de developpement de cet outil n'avait pas d'acces sortant vers
wikipedia.org ni wikidata.org (refus 403 de la politique d'egress). Fabriquer
des chiffres presentes comme empiriques aurait ete la seule autre option. Elle
n'a pas ete retenue.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from .calibration import synthetic_qid, zipf_weights
from .domain.models import (
    ArticleSnapshot,
    ConceptObservation,
    EntityDossier,
    Provenance,
    RevisionRecord,
)
from .metrics.divergence import _multinomial

_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)

# Blocs thematiques du scenario. Chaque bloc regroupe des concepts qu'une
# edition traite ensemble ou pas du tout - c'est la structure que l'analyse doit
# retrouver.
_BLOCKS: dict[str, list[str]] = {
    "defense-collective": [
        "Defense collective", "Article 5", "Commandement integre",
        "Conseil de l'Atlantique Nord", "Traite de Washington", "Dissuasion",
    ],
    "elargissement": [
        "Elargissement de l'Alliance", "Adhesion", "Plan d'action pour l'adhesion",
        "Politique de la porte ouverte", "Candidature", "Ratification",
    ],
    "heritage-guerre-froide": [
        "Pacte de Varsovie", "Guerre froide", "Rideau de fer", "Course aux armements",
        "Detente", "Dissolution de l'URSS",
    ],
    "operations": [
        "Operation aerienne au Kosovo", "Mission en Afghanistan",
        "Intervention en Libye", "Maintien de la paix", "Police du ciel balte",
        "Groupements tactiques",
    ],
    "critiques": [
        "Controverses sur l'expansion", "Dommages collateraux",
        "Critiques de l'unilateralisme", "Debat sur le partage du fardeau",
        "Opposition interne", "Souverainete nationale",
    ],
    "institutions": [
        "Union europeenne", "Organisation des Nations unies",
        "Partenariat pour la paix", "Budget commun", "Etats membres",
        "Secretaire general",
    ],
}

# Profils de cadrage : part d'attention accordee a chaque bloc par edition.
# Ces profils sont POSES, pas mesures. Ils constituent la structure que le
# scenario injecte, et donc la verite terrain de la demonstration.
_PROFILES: dict[str, dict[str, float]] = {
    "en": {"defense-collective": 5, "elargissement": 3, "heritage-guerre-froide": 2,
           "operations": 3, "critiques": 1, "institutions": 4},
    "fr": {"defense-collective": 4, "elargissement": 2, "heritage-guerre-froide": 2,
           "operations": 3, "critiques": 2, "institutions": 5},
    "de": {"defense-collective": 4, "elargissement": 2, "heritage-guerre-froide": 3,
           "operations": 2, "critiques": 3, "institutions": 4},
    "ru": {"defense-collective": 2, "elargissement": 5, "heritage-guerre-froide": 5,
           "operations": 4, "critiques": 4, "institutions": 1},
    "pl": {"defense-collective": 5, "elargissement": 5, "heritage-guerre-froide": 4,
           "operations": 2, "critiques": 1, "institutions": 2},
    "uk": {"defense-collective": 4, "elargissement": 6, "heritage-guerre-froide": 3,
           "operations": 2, "critiques": 1, "institutions": 3},
}

# Longueur d'article et intensite du conflit editorial par edition. Poses
# egalement : ils font varier les regimes d'echantillonnage pour que la
# demonstration montre des intervalles de largeurs differentes.
_EDITION_PROFILE: dict[str, dict[str, int]] = {
    "en": {"observations": 1400, "revisions": 400, "reverts": 22},
    "fr": {"observations": 760, "revisions": 190, "reverts": 7},
    "de": {"observations": 880, "revisions": 240, "reverts": 11},
    "ru": {"observations": 640, "revisions": 320, "reverts": 41},
    "pl": {"observations": 520, "revisions": 150, "reverts": 9},
    "uk": {"observations": 430, "revisions": 260, "reverts": 33},
}

DEMO_ENTITY_QID = synthetic_qid(999_000)


def _concept_catalogue() -> tuple[list[str], dict[str, str], dict[str, list[int]]]:
    """Espace conceptuel du scenario : QID reserves, libelles, indices par bloc."""
    space: list[str] = []
    labels: dict[str, str] = {}
    by_block: dict[str, list[int]] = {}

    cursor = 500_000
    for block, names in _BLOCKS.items():
        indexes: list[int] = []
        for name in names:
            qid = synthetic_qid(cursor)
            space.append(qid)
            labels[qid] = name
            indexes.append(len(space) - 1)
            cursor += 1
        by_block[block] = indexes

    return space, labels, by_block


def _revisions(lang: str, count: int, reverts: int, rng: random.Random) -> list[RevisionRecord]:
    """Historique synthetique avec conflit editorial dose."""
    editors = [f"{lang}_contributeur_{i}" for i in range(12)]
    revisions: list[RevisionRecord] = []
    for i in range(count):
        revisions.append(
            RevisionRecord(
                rev_id=500_000 + i,
                timestamp=_EPOCH + timedelta(days=i * 2, hours=rng.randint(0, 23)),
                sha1=hashlib.sha1(f"{lang}|{i}".encode()).hexdigest(),
                size=30_000 + rng.randint(-2_000, 2_000),
                editor=editors[rng.randrange(len(editors))],
                is_anonymous=rng.random() < 0.12,
                is_minor=rng.random() < 0.3,
            )
        )

    # Les reverts sont plantes par paires opposees, de facon que l'indice de
    # revert mutuel soit non trivial : deux contributeurs qui se defont
    # reciproquement, ce qui est la signature d'un conflit et non d'une
    # patrouille anti-vandalisme.
    if reverts > 0 and count > 12:
        step = max(4, count // (reverts + 1))
        for k in range(reverts):
            position = min(count - 1, step * (k + 1))
            target = position - 2
            if target < 1:
                continue
            antagonist = editors[k % 4]
            protagonist = editors[(k % 4) + 4]
            revisions[target] = RevisionRecord(
                rev_id=revisions[target].rev_id,
                timestamp=revisions[target].timestamp,
                sha1=revisions[target].sha1,
                size=revisions[target].size,
                editor=protagonist if k % 2 else antagonist,
                is_anonymous=False,
            )
            revisions[position] = RevisionRecord(
                rev_id=revisions[position].rev_id,
                timestamp=revisions[position].timestamp,
                sha1=revisions[position - 3].sha1,
                size=revisions[position - 3].size,
                editor=antagonist if k % 2 else protagonist,
                is_anonymous=False,
            )
    return revisions


def build_demo_dossier(seed: int = 20260912) -> EntityDossier:
    """Construit le dossier de demonstration, de facon deterministe."""
    rng = random.Random(seed)
    space, labels, by_block = _concept_catalogue()
    within = zipf_weights(max(len(v) for v in by_block.values()), exponent=0.9)

    snapshots: list[ArticleSnapshot] = []
    for position, (lang, profile) in enumerate(_PROFILES.items()):
        total_weight = sum(profile.values())
        distribution = [0.0] * len(space)
        for block, weight in profile.items():
            share = weight / total_weight
            indexes = by_block[block]
            for offset, index in enumerate(indexes):
                distribution[index] = share * within[offset]

        normalizer = sum(distribution)
        distribution = [value / normalizer for value in distribution]

        edition = _EDITION_PROFILE[lang]
        draws = _multinomial(rng, edition["observations"], distribution)

        # Repartition structurelle : les concepts les plus frequents d'une
        # edition ont plus de chances d'apparaitre en introduction.
        observations: list[ConceptObservation] = []
        for index, count in enumerate(draws):
            if count <= 0:
                continue
            lead = int(count * 0.25) if count >= 4 else 0
            if lead:
                observations.append(
                    ConceptObservation(qid=space[index], count=lead, section="lead")
                )
            observations.append(
                ConceptObservation(
                    qid=space[index], count=int(count) - lead, section="body"
                )
            )

        snapshots.append(
            ArticleSnapshot(
                lang=lang,
                title=f"[DEMO] article {lang}",
                entity_qid=DEMO_ENTITY_QID,
                revision_id=900_000 + position,
                revision_timestamp=_EPOCH + timedelta(days=edition["revisions"] * 2),
                revision_sha1=hashlib.sha1(f"head|{lang}".encode()).hexdigest(),
                byte_size=edition["observations"] * 45,
                concepts=tuple(observations),
                revisions=tuple(
                    _revisions(lang, edition["revisions"], edition["reverts"], rng)
                ),
                provenance=Provenance(
                    source_id="local:synthetic-demo",
                    retrieved_at=_EPOCH,
                    endpoint="prisme.scenarios.build_demo_dossier",
                    notes="Corpus genere. Aucune valeur empirique.",
                ),
            )
        )

    return EntityDossier(
        entity_qid=DEMO_ENTITY_QID,
        label="[DEMO] Entite illustrative - organisation de securite collective",
        snapshots=tuple(snapshots),
        concept_labels=labels,
        collected_at=_EPOCH,
        corpus_id="demo-synthetique",
    )


def ground_truth_profiles() -> Mapping[str, Mapping[str, float]]:
    """Profils de cadrage injectes, normalises. Verite terrain du scenario.

    Exposee pour que la demonstration puisse etre confrontee a ce qu'elle
    contient reellement : un lecteur doit pouvoir verifier que ce que PRISME
    remonte correspond a ce qui a ete pose, et non a ce qu'on souhaitait lire.
    """
    return {
        lang: {
            block: weight / sum(profile.values()) for block, weight in profile.items()
        }
        for lang, profile in _PROFILES.items()
    }
