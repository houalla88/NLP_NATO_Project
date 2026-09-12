"""Banc d'etalonnage : verifier que l'instrument mesure ce qu'il pretend mesurer.

Le probleme que ce module resout
--------------------------------
Une chaine NLP appliquee a un corpus reel produit toujours des chiffres. Rien,
dans le chiffre lui-meme, ne dit s'il reflete le phenomene etudie ou une
propriete de la chaine de traitement. En l'absence de verite terrain, une
divergence de 0,31 est indistinguable d'un artefact de tokenisation.

La reponse classique en metrologie est l'etalon : on fait passer a l'instrument
un objet dont la valeur est connue et on verifie qu'il la restitue. C'est ce
que fait ce module. Il genere des corpus dont la distribution generatrice est
connue exactement, donc dont la divergence vraie est calculable en forme close,
puis verifie que la mesure la retrouve.

Les cinq controles
------------------
1. Justesse       - la JSD mesuree retrouve la JSD vraie.
2. Couverture     - l'intervalle bootstrap contient la valeur vraie dans la
                    proportion annoncee (95 %).
3. Calibration du - deux editions tirees de la MEME loi ne sont declarees
   test nul         divergentes qu'au taux d'erreur nominal (5 %).
4. Rappel des     - les concepts injectes exclusivement dans une edition sont
   distinctifs      bien remontes par la methode log-odds.
5. Reverts        - le detecteur retrouve exactement les retours arriere plantes.

Le controle 3 est le plus important. Un instrument qui declare significative
une divergence entre deux echantillons d'une meme population produit des
conclusions a partir de bruit. C'est le mode de defaillance le plus courant et
le moins visible des analyses de corpus.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from .domain.models import (
    ArticleSnapshot,
    ConceptObservation,
    EntityDossier,
    Provenance,
    RevisionRecord,
)
from .metrics.contestedness import detect_identity_reverts
from .metrics.distinctive import fightin_words
from .metrics.divergence import (
    UncertaintyConfig,
    _multinomial,
    bootstrap_interval,
    jensen_shannon,
    jensen_shannon_corrected,
    permutation_p_value,
)

# Plage de QID reservee aux corpus synthetiques. Ces identifiants n'existent
# pas sur Wikidata : toute tentative de les resoudre echoue bruyamment. C'est
# volontaire - un chiffre synthetique ne doit jamais pouvoir etre confondu avec
# une observation, meme apres avoir transite par un export ou une capture.
SYNTHETIC_QID_BASE = 900_000_000

_EPOCH = datetime(2019, 1, 1, tzinfo=timezone.utc)


def synthetic_qid(index: int) -> str:
    return f"Q{SYNTHETIC_QID_BASE + index}"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def zipf_weights(size: int, exponent: float = 1.1) -> list[float]:
    """Poids en loi de puissance, normalises.

    Les frequences de concepts dans un texte reel sont a queue lourde. Etalonner
    sur une loi uniforme rendrait le banc trop facile et masquerait precisement
    le regime - les concepts rares - ou les estimateurs sont fragiles.
    """
    raw = [1.0 / ((i + 1) ** exponent) for i in range(size)]
    total = sum(raw)
    return [value / total for value in raw]


@dataclass(frozen=True, slots=True)
class EditionSpec:
    """Profil generatif d'une edition synthetique.

    `block_weights` repartit la masse d'attention entre blocs thematiques.
    Deux editions au meme profil sont statistiquement indiscernables ; c'est le
    cas de reference du controle nul.
    """

    lang: str
    block_weights: Sequence[float]
    n_observations: int = 600
    exclusive_concepts: int = 0


@dataclass(frozen=True, slots=True)
class SyntheticCorpus:
    """Corpus genere, accompagne de sa verite terrain."""

    dossier: EntityDossier
    true_distributions: Mapping[str, list[float]]
    concept_space: list[str]
    exclusive_by_lang: Mapping[str, list[str]]
    planted_reverts: Mapping[str, int]

    def true_jsd(self, lang_a: str, lang_b: str) -> float:
        """Divergence vraie entre deux editions, calculee sur les lois generatrices."""
        return jensen_shannon(self.true_distributions[lang_a], self.true_distributions[lang_b])


def build_synthetic_corpus(
    specs: Sequence[EditionSpec],
    n_blocks: int = 6,
    concepts_per_block: int = 20,
    seed: int = 1234,
    revisions_per_edition: int = 120,
    planted_reverts: int = 8,
    corpus_id: str = "calibration",
) -> SyntheticCorpus:
    """Genere un corpus dont la loi generatrice de chaque edition est connue.

    Construction : l'espace conceptuel est partitionne en blocs thematiques ;
    chaque edition repartit son attention entre blocs selon `block_weights`,
    et suit une loi de Zipf a l'interieur de chaque bloc. Les observations sont
    ensuite tirees multinomialement. La loi vraie etant explicite, la divergence
    vraie est exacte, et non estimee.
    """
    rng = random.Random(seed)
    total_concepts = n_blocks * concepts_per_block
    base_space = [synthetic_qid(i) for i in range(total_concepts)]

    # Concepts exclusifs : places hors de l'espace partage, ils constituent la
    # verite terrain du controle de rappel des distinctifs.
    exclusive_by_lang: dict[str, list[str]] = {}
    cursor = total_concepts
    for spec in specs:
        if spec.exclusive_concepts > 0:
            exclusive_by_lang[spec.lang] = [
                synthetic_qid(cursor + k) for k in range(spec.exclusive_concepts)
            ]
            cursor += spec.exclusive_concepts
        else:
            exclusive_by_lang[spec.lang] = []

    space = base_space + [q for qids in exclusive_by_lang.values() for q in qids]
    index = {qid: i for i, qid in enumerate(space)}
    within = zipf_weights(concepts_per_block)

    true_distributions: dict[str, list[float]] = {}
    snapshots: list[ArticleSnapshot] = []
    labels: dict[str, str] = {}

    for position, spec in enumerate(specs):
        weights = list(spec.block_weights)
        if len(weights) != n_blocks:
            raise ValueError(
                f"{spec.lang}: {len(weights)} poids de blocs pour {n_blocks} blocs"
            )
        total_weight = sum(weights)
        if total_weight <= 0:
            raise ValueError(f"{spec.lang}: poids de blocs tous nuls")
        weights = [w / total_weight for w in weights]

        distribution = [0.0] * len(space)
        for block, block_weight in enumerate(weights):
            for offset, share in enumerate(within):
                distribution[block * concepts_per_block + offset] = block_weight * share

        # Les concepts exclusifs recoivent une part fixe, prelevee au prorata
        # sur le reste : la loi reste normalisee et la part est connue.
        exclusives = exclusive_by_lang[spec.lang]
        if exclusives:
            share_each = 0.02
            reserved = share_each * len(exclusives)
            distribution = [p * (1.0 - reserved) for p in distribution]
            for qid in exclusives:
                distribution[index[qid]] = share_each

        true_distributions[spec.lang] = distribution

        draws = _multinomial(rng, spec.n_observations, distribution)
        observations = tuple(
            ConceptObservation(qid=space[i], count=int(count), section="body")
            for i, count in enumerate(draws)
            if count > 0
        )

        for qid in space:
            labels.setdefault(qid, f"concept synthetique {qid}")

        snapshots.append(
            ArticleSnapshot(
                lang=spec.lang,
                title=f"synthetic-{spec.lang}",
                entity_qid=synthetic_qid(0),
                revision_id=1000 + position,
                revision_timestamp=_EPOCH,
                revision_sha1="",
                byte_size=spec.n_observations * 40,
                concepts=observations,
                revisions=tuple(
                    _synthetic_revisions(
                        spec.lang, revisions_per_edition, planted_reverts, rng
                    )
                ),
                provenance=Provenance(
                    source_id="local:synthetic-validation",
                    retrieved_at=_EPOCH,
                    endpoint="prisme.calibration",
                    notes="Corpus genere. Aucune valeur empirique.",
                ),
            )
        )

    dossier = EntityDossier(
        entity_qid=synthetic_qid(0),
        label="Entite synthetique d'etalonnage",
        snapshots=tuple(snapshots),
        concept_labels=labels,
        collected_at=_EPOCH,
        corpus_id=corpus_id,
    )

    return SyntheticCorpus(
        dossier=dossier,
        true_distributions=true_distributions,
        concept_space=space,
        exclusive_by_lang=exclusive_by_lang,
        planted_reverts={spec.lang: planted_reverts for spec in specs},
    )


def _synthetic_revisions(
    lang: str, count: int, planted: int, rng: random.Random
) -> list[RevisionRecord]:
    """Historique synthetique contenant exactement `planted` reverts d'identite.

    Chaque revision recoit une empreinte unique, sauf aux positions choisies ou
    l'empreinte d'une revision anterieure est reproduite - ce qui est la
    signature exacte d'un retour arriere.
    """
    editors = [f"{lang}-editeur-{i}" for i in range(8)]
    revisions: list[RevisionRecord] = []
    digests: list[str] = []

    for i in range(count):
        digest = hashlib.sha1(f"{lang}:{i}".encode()).hexdigest()
        digests.append(digest)
        revisions.append(
            RevisionRecord(
                rev_id=10_000 + i,
                timestamp=_EPOCH + timedelta(days=i * 3),
                sha1=digest,
                size=20_000 + rng.randint(-500, 500),
                editor=editors[i % len(editors)],
                is_anonymous=(i % 11 == 0),
            )
        )

    # Positions de plantation espacees, a distance >= 2 de la cible restauree
    # pour satisfaire la definition du detecteur.
    if planted > 0 and count > 10:
        step = max(3, count // (planted + 1))
        for k in range(planted):
            position = min(count - 1, step * (k + 1))
            target = position - 2
            if target < 0:
                continue
            restored = revisions[target].sha1
            revisions[position] = RevisionRecord(
                rev_id=revisions[position].rev_id,
                timestamp=revisions[position].timestamp,
                sha1=restored,
                size=revisions[target].size,
                editor=editors[(position + 3) % len(editors)],
                is_anonymous=False,
            )

    return revisions


# ---------------------------------------------------------------------------
# Controles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    """Resultat d'un controle d'etalonnage."""

    name: str
    passed: bool
    observed: float
    expected: str
    detail: str = ""

    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] {self.name:<34} observe={self.observed:<10.4f} attendu {self.expected}"


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    checks: tuple[Check, ...]
    seed: int

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def report(self) -> str:
        lines = [check.line() for check in self.checks]
        lines.append("")
        lines.append("ETALONNAGE : " + ("CONFORME" if self.passed else "NON CONFORME"))
        return "\n".join(lines)


def _counts_vector(snapshot: ArticleSnapshot, space: Sequence[str]) -> list[float]:
    by_qid = {c.qid: float(c.count) for c in snapshot.concepts}
    return [by_qid.get(qid, 0.0) for qid in space]


def check_accuracy_and_coverage(
    corpus: SyntheticCorpus, config: UncertaintyConfig
) -> list[Check]:
    """Controles 1 et 2 : justesse ponctuelle et couverture de l'intervalle."""
    dossier = corpus.dossier
    space = corpus.concept_space
    errors: list[float] = []
    covered = 0
    total = 0

    langs = list(dossier.langs)
    for i, lang_a in enumerate(langs):
        for lang_b in langs[i + 1 :]:
            counts_a = _counts_vector(dossier.by_lang(lang_a), space)
            counts_b = _counts_vector(dossier.by_lang(lang_b), space)
            measured = jensen_shannon_corrected(counts_a, counts_b)
            truth = corpus.true_jsd(lang_a, lang_b)
            errors.append(abs(measured - truth))

            interval = bootstrap_interval(counts_a, counts_b, config)
            total += 1
            if interval and interval.lower <= measured <= interval.upper:
                covered += 1

    mean_error = sum(errors) / len(errors) if errors else 1.0
    contains_point = covered / total if total else 0.0

    return [
        Check(
            name="justesse (erreur absolue moyenne)",
            passed=mean_error < 0.05,
            observed=mean_error,
            expected="< 0.05",
            detail=(
                "Ecart entre la JSD estimee sur echantillon et la JSD vraie des lois "
                "generatrices. C'est ce controle, et lui seul, qui borne le biais "
                "residuel apres correction de Miller-Madow."
            ),
        ),
        Check(
            name="intervalle contenant l'estimation",
            passed=contains_point == 1.0,
            observed=contains_point,
            expected="= 1.00",
            detail=(
                "Garde-fou elementaire : un intervalle qui ne contient pas son propre "
                "point estime est inexploitable. Le bootstrap percentile brut echouait "
                "ici, ce qui a motive la construction par transplantation de dispersion."
            ),
        ),
    ]


def check_null_calibration(
    trials: int = 100,
    n_observations: int = 500,
    alpha: float = 0.05,
    tolerance: float = 2.0,
    seed: int = 99,
) -> Check:
    """Controle 3 : taux de faux positifs du test de permutation.

    Deux editions sont generees a partir d'une seule et meme loi. Le test ne
    doit les declarer divergentes que dans environ `alpha` des essais. Un taux
    nettement superieur signifierait que l'outil transforme du bruit en constat.
    """
    rng = random.Random(seed)
    distribution = zipf_weights(120, exponent=1.05)
    rejections = 0

    for trial in range(trials):
        counts_a = _multinomial(rng, n_observations, distribution)
        counts_b = _multinomial(rng, n_observations, distribution)
        observed = jensen_shannon_corrected(counts_a, counts_b)
        p_value, _ = permutation_p_value(
            counts_a,
            counts_b,
            observed,
            UncertaintyConfig(bootstrap=0, permutations=200, seed=seed + trial),
        )
        if p_value is not None and p_value < alpha:
            rejections += 1

    rate = rejections / trials
    # Le test etant exact, le taux attendu est alpha. La borne est posee a
    # `tolerance` * alpha pour absorber le bruit de Monte-Carlo sur un nombre
    # fini d'essais, pas pour tolerer un ecart de methode : c'est ce controle
    # qui a revele qu'une version parametrique anterieure rejetait a 15,5 %.
    return Check(
        name="taux de faux positifs (test nul)",
        passed=rate <= tolerance * alpha,
        observed=rate,
        expected=f"<= {tolerance * alpha:.2f}",
        detail=(
            "Deux editions tirees de la meme loi. Un taux eleve signifierait que "
            "l'outil declare significatives des divergences qui n'existent pas."
        ),
    )


def check_monotonicity(seed: int = 2026) -> Check:
    """Controle complementaire : la mesure croit avec la separation injectee.

    Une mesure juste en moyenne mais non monotone serait inutilisable pour
    classer des editions entre elles - or c'est l'usage principal.
    """
    separations = [0.0, 0.15, 0.3, 0.5, 0.75, 1.0]
    replications = 5
    measured: list[float] = []

    # La monotonie est une propriete de l'ESPERANCE de l'estimateur, pas d'un
    # tirage isole. L'exiger sur un tirage unique reviendrait a faire echouer le
    # banc sur du bruit d'echantillonnage - et, pire, a inciter a rendre
    # l'estimateur artificiellement lisse pour satisfaire le controle.
    for step, separation in enumerate(separations):
        base = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        shifted = [1.0 + separation * 4 if i < 2 else 1.0 for i in range(6)]
        draws: list[float] = []
        for replicate in range(replications):
            corpus = build_synthetic_corpus(
                specs=[
                    EditionSpec("aa", base, n_observations=800),
                    EditionSpec("bb", shifted, n_observations=800),
                ],
                seed=seed + step * 100 + replicate,
                planted_reverts=0,
                revisions_per_edition=0,
            )
            space = corpus.concept_space
            draws.append(
                jensen_shannon_corrected(
                    _counts_vector(corpus.dossier.by_lang("aa"), space),
                    _counts_vector(corpus.dossier.by_lang("bb"), space),
                )
            )
        measured.append(sum(draws) / len(draws))

    inversions = sum(
        1 for i in range(len(measured) - 1) if measured[i + 1] < measured[i] - 1e-9
    )
    return Check(
        name="monotonie vs separation injectee",
        passed=inversions == 0,
        observed=float(inversions),
        expected="0 inversion",
        detail=f"serie mesuree : {[round(v, 4) for v in measured]}",
    )


def check_distinctive_recall(corpus: SyntheticCorpus) -> Check:
    """Controle 4 : rappel des concepts injectes exclusivement dans une edition."""
    dossier = corpus.dossier
    space = corpus.concept_space

    per_lang = {
        s.lang: {c.qid: float(c.count) for c in s.concepts} for s in dossier.snapshots
    }
    background: dict[str, float] = {}
    for counts in per_lang.values():
        for qid, value in counts.items():
            background[qid] = background.get(qid, 0.0) + value

    recalled = 0
    planted = 0
    for lang, exclusives in corpus.exclusive_by_lang.items():
        if not exclusives:
            continue
        counts_out: dict[str, float] = {}
        for other, counts in per_lang.items():
            if other == lang:
                continue
            for qid, value in counts.items():
                counts_out[qid] = counts_out.get(qid, 0.0) + value

        scored = fightin_words(per_lang[lang], counts_out, background, lang)
        top = {d.qid for d in scored[: max(10, len(exclusives) * 2)] if d.z_score > 0}
        planted += len(exclusives)
        recalled += len(top & set(exclusives))

    rate = recalled / planted if planted else 1.0
    return Check(
        name="rappel des concepts distinctifs",
        passed=rate >= 0.80,
        observed=rate,
        expected=">= 0.80",
        detail=(
            f"{recalled}/{planted} concepts injectes en exclusivite retrouves dans le "
            "haut du classement log-odds."
        ),
    )


def check_revert_detection(corpus: SyntheticCorpus) -> Check:
    """Controle 5 : le detecteur retrouve exactement les reverts plantes."""
    exact = 0
    total = 0
    for snapshot in corpus.dossier.snapshots:
        expected = corpus.planted_reverts.get(snapshot.lang, 0)
        if expected <= 0:
            continue
        total += 1
        detected = len(detect_identity_reverts(snapshot.revisions))
        if detected == expected:
            exact += 1

    rate = exact / total if total else 1.0
    return Check(
        name="detection des retours arriere",
        passed=rate == 1.0,
        observed=rate,
        expected="= 1.00 (exact)",
        detail="Les reverts sont plantes par reproduction d'empreinte SHA-1.",
    )


def run_calibration(seed: int = 4242, fast: bool = False) -> CalibrationResult:
    """Execute le banc complet et renvoie le verdict."""
    config = UncertaintyConfig(
        bootstrap=120 if fast else 300,
        permutations=120 if fast else 300,
        seed=seed,
    )

    corpus = build_synthetic_corpus(
        specs=[
            EditionSpec("aa", [5, 3, 1, 1, 1, 1], n_observations=900, exclusive_concepts=4),
            EditionSpec("bb", [1, 1, 5, 3, 1, 1], n_observations=750, exclusive_concepts=4),
            EditionSpec("cc", [1, 1, 1, 1, 5, 3], n_observations=600, exclusive_concepts=4),
            EditionSpec("dd", [3, 3, 2, 2, 2, 2], n_observations=850),
        ],
        seed=seed,
    )

    checks: list[Check] = []
    checks.extend(check_accuracy_and_coverage(corpus, config))
    checks.append(
        check_null_calibration(
            trials=25 if fast else 100,
            tolerance=3.0 if fast else 2.0,
            seed=seed,
        )
    )
    checks.append(check_monotonicity(seed=seed))
    checks.append(check_distinctive_recall(corpus))
    checks.append(check_revert_detection(corpus))

    return CalibrationResult(checks=tuple(checks), seed=seed)
