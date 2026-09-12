"""Divergence entre distributions conceptuelles, avec quantification de l'incertitude.

Choix de la mesure
------------------
La divergence de Kullback-Leibler est ecartee : elle est asymetrique (KL(P||Q)
!= KL(Q||P), donc « le russe s'ecarte de l'anglais » et l'inverse donneraient
deux chiffres differents) et infinie des qu'un concept est absent d'un cote.
Or l'absence d'un concept est precisement un cas frequent et interessant ici.

La divergence de Jensen-Shannon (Lin, 1991) corrige les deux defauts : elle est
symetrique, toujours finie, et bornee dans [0, 1] en base 2. Sa racine carree
est une metrique au sens mathematique (Endres & Schindelin, 2003), ce qui
autorise a projeter la matrice des distances par positionnement multidimensionnel
sans violer les hypotheses de la methode.

Pourquoi l'incertitude n'est pas optionnelle
--------------------------------------------
Deux echantillons tires d'une *meme* distribution produisent une JSD nettement
superieure a zero des que le support est large et les effectifs modestes. Un
chiffre de divergence brut est donc ininterpretable seul. Deux dispositifs sont
fournis :

- un bootstrap non parametrique, qui donne l'intervalle de confiance de la
  divergence observee ;
- un test de permutation parametrique, qui donne la probabilite d'observer une
  divergence au moins aussi grande si les deux editions puisaient dans une
  distribution commune.

C'est la conjonction des deux qui permet d'ecrire « cet ecart de cadrage est
mesure » plutot que « ce chiffre est grand ».
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..domain.errors import ConfigurationError
from ..domain.models import (
    ConceptDistribution,
    DivergenceMatrix,
    DivergencePair,
    Interval,
)

# L'approximation normale du binomial n'est employee que lorsque LES DEUX
# queues sont fournies (n*p >= 30 ET n*(1-p) >= 30). En deca, un tirage exact
# est utilise : une gaussienne arrondie puis tronquee a zero reproduit mal une
# loi de faible moyenne (elle est symetrique la ou le binomial est asymetrique),
# et cette distorsion se propage directement dans les queues de la distribution
# nulle - donc dans les p-valeurs. Le banc d'etalonnage
# (`prisme.calibration.check_null_calibration`) est precisement le controle qui
# detecte une regression sur ce point.
_NORMAL_APPROX_THRESHOLD = 30.0


def jensen_shannon(p: Sequence[float], q: Sequence[float]) -> float:
    """JSD en base 2, dans [0, 1]. 0 = distributions identiques.

    JSD(P||Q) = H((P+Q)/2) - (H(P) + H(Q))/2
    """
    if len(p) != len(q):
        raise ConfigurationError("distributions de longueurs differentes")
    total = 0.0
    for pi, qi in zip(p, q):
        mi = 0.5 * (pi + qi)
        if mi <= 0:
            continue
        if pi > 0:
            total += 0.5 * pi * math.log2(pi / mi)
        if qi > 0:
            total += 0.5 * qi * math.log2(qi / mi)
    # Les erreurs d'arrondi flottantes peuvent sortir infinitesimalement
    # de [0, 1] ; on borne plutot que de propager une valeur hors domaine.
    return min(1.0, max(0.0, total))


def _entropy_bits(distribution: Sequence[float]) -> float:
    return -sum(x * math.log2(x) for x in distribution if x > 0)


def jensen_shannon_corrected(
    counts_a: Sequence[float], counts_b: Sequence[float]
) -> float:
    """JSD corrigee du biais de sous-echantillonnage (Miller-Madow).

    Le probleme
    -----------
    L'estimateur naif - calculer la JSD sur les frequences observees - est
    biaise vers le haut, et le biais est loin d'etre negligeable. Sur deux
    echantillons de 900 occurrences tires de la MEME loi a queue lourde, il
    renvoie environ 0,058 la ou la vraie valeur est 0. Autrement dit, il
    produit spontanement de la divergence la ou il n'y en a aucune, et d'autant
    plus que les articles compares sont courts ou le support large. Un
    classement d'editions etabli sur cet estimateur classe en partie les
    longueurs d'articles.

    La cause est connue : l'entropie de Shannon est concave, donc son
    estimateur par substitution sous-estime systematiquement l'entropie vraie
    d'environ (K-1)/(2n) nats, ou K est le nombre de categories observees
    (Miller, 1955 ; synthese dans Paninski, 2003, Neural Computation 15(6)).
    Comme JSD = H(M) - [H(P) + H(Q)]/2, les trois termes sont biaises, mais pas
    de la meme quantite : les deux termes soustraits reposent sur n_a et n_b
    observations, le terme H(M) sur davantage. Le desequilibre ne se compense
    pas et laisse un residu positif.

    La correction
    -------------
    La correction de Miller-Madow est appliquee separement aux trois entropies.
    L'effectif attribue au melange M = (P + Q)/2 est celui qui reproduit sa
    variance reelle :

        n_M = 4 * n_a * n_b / (n_a + n_b)

    c'est-a-dire 2n lorsque les deux editions ont le meme nombre d'occurrences.

    Limites
    -------
    La correction est asymptotique, au premier ordre en 1/n. Elle reduit
    fortement le biais sans l'annuler, et peut faire passer l'estimation
    legerement sous zero pour deux echantillons quasi identiques - la valeur
    est alors bornee a zero. Elle ne remplace pas le test de permutation :
    corriger le biais et prouver qu'un ecart depasse le bruit sont deux
    questions distinctes.
    """
    n_a, n_b = sum(counts_a), sum(counts_b)
    if n_a <= 0 or n_b <= 0:
        return 0.0

    p = [c / n_a for c in counts_a]
    q = [c / n_b for c in counts_b]
    m = [0.5 * (pi + qi) for pi, qi in zip(p, q)]

    support_a = sum(1 for c in counts_a if c > 0)
    support_b = sum(1 for c in counts_b if c > 0)
    support_m = sum(1 for x in m if x > 0)
    n_m = 4.0 * n_a * n_b / (n_a + n_b)

    # (K - 1) / (2n) nats, converti en bits.
    def correction(support: int, effective_n: float) -> float:
        if effective_n <= 0:
            return 0.0
        return (support - 1) / (2.0 * effective_n * math.log(2.0))

    corrected = (
        _entropy_bits(m) + correction(support_m, n_m)
        - 0.5 * (_entropy_bits(p) + correction(support_a, n_a))
        - 0.5 * (_entropy_bits(q) + correction(support_b, n_b))
    )
    return min(1.0, max(0.0, corrected))


def hellinger(p: Sequence[float], q: Sequence[float]) -> float:
    """Distance de Hellinger, dans [0, 1].

    Fournie en contre-mesure : elle pondere differemment les petites
    probabilites. Un classement de paires stable entre JSD et Hellinger est un
    signe que le resultat ne depend pas du choix de la mesure.
    """
    accumulator = sum((math.sqrt(pi) - math.sqrt(qi)) ** 2 for pi, qi in zip(p, q))
    return min(1.0, math.sqrt(accumulator / 2.0))


def overlap(p: Sequence[float], q: Sequence[float]) -> float:
    """Masse d'attention partagee : somme des minima, dans [0, 1].

    Lecture directe et non technique : « les deux editions consacrent 62 % de
    leur attention aux memes concepts ». C'est le chiffre a montrer a un
    interlocuteur non statisticien.
    """
    return sum(min(pi, qi) for pi, qi in zip(p, q))


# ---------------------------------------------------------------------------
# Echantillonnage
# ---------------------------------------------------------------------------


def _binomial(rng: random.Random, n: int, p: float) -> int:
    """Tirage binomial exact en petite moyenne, normal en grande.

    Sous le seuil, l'algorithme BINV (inversion de la fonction de repartition,
    Kachitvichyanukul & Schmeiser, 1988) est employe : son cout attendu est
    O(n*p) et non O(n), ce qui le rend utilisable sur un support de plusieurs
    milliers de concepts dont la quasi-totalite a une moyenne inferieure a 1.

    La symetrie B(n, p) = n - B(n, 1-p) est exploitee pour que p > 1/2 reste
    dans le regime rapide.
    """
    if n <= 0 or p <= 0.0:
        return 0
    if p >= 1.0:
        return n
    if p > 0.5:
        return n - _binomial(rng, n, 1.0 - p)

    mean = n * p
    if mean >= _NORMAL_APPROX_THRESHOLD and n * (1.0 - p) >= _NORMAL_APPROX_THRESHOLD:
        sigma = math.sqrt(mean * (1.0 - p))
        return min(n, max(0, int(round(rng.gauss(mean, sigma)))))

    # BINV. `probability` porte P(X = x), accumule dans `cumulative`.
    q = 1.0 - p
    ratio = p / q
    increment = (n + 1) * ratio
    probability = q**n
    if probability <= 0.0:
        # Sous-depassement (n tres grand) : repli sur la normale, seul cas ou
        # BINV n'est pas numeriquement exploitable.
        sigma = math.sqrt(mean * q)
        return min(n, max(0, int(round(rng.gauss(mean, sigma)))))

    u = rng.random()
    x = 0
    while u > probability and x < n:
        u -= probability
        x += 1
        probability *= increment / x - ratio
        if probability <= 0.0:
            break
    return min(x, n)


def _multinomial(
    rng: random.Random, n: int, probabilities: Sequence[float]
) -> list[float]:
    """Tirage multinomial par decomposition en binomiales conditionnelles.

    Cout O(K) et non O(n) : indispensable pour que quelques centaines de
    replications restent instantanees sur un support de plusieurs milliers de
    concepts.
    """
    counts = [0.0] * len(probabilities)
    remaining_n = n
    remaining_p = sum(probabilities)
    for index, prob in enumerate(probabilities):
        if remaining_n <= 0 or remaining_p <= 0:
            break
        conditional = min(1.0, max(0.0, prob / remaining_p))
        drawn = _binomial(rng, remaining_n, conditional)
        counts[index] = float(drawn)
        remaining_n -= drawn
        remaining_p -= prob
    return counts


def _normalize(counts: Sequence[float]) -> list[float]:
    total = sum(counts)
    if total <= 0:
        return [0.0] * len(counts)
    return [c / total for c in counts]


# ---------------------------------------------------------------------------
# Incertitude
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UncertaintyConfig:
    """Parametrage de l'inference. Expose pour etre trace dans le rapport."""

    bootstrap: int = 400
    permutations: int = 400
    level: float = 0.95
    seed: int = 20260912

    def __post_init__(self) -> None:
        if not 0.5 < self.level < 1.0:
            raise ConfigurationError(f"niveau de confiance invalide : {self.level}")
        if self.bootstrap < 0 or self.permutations < 0:
            raise ConfigurationError("nombre de replications negatif")


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Percentile par interpolation lineaire sur un echantillon trie."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[int(position)]
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def bootstrap_interval(
    counts_a: Sequence[float],
    counts_b: Sequence[float],
    config: UncertaintyConfig,
) -> Interval | None:
    """Intervalle de DISPERSION de la JSD, par bootstrap multinomial.

    Ce que l'intervalle dit
    -----------------------
    « De combien ce chiffre bougerait-il si les deux articles etaient un autre
    tirage de meme longueur ? » C'est une mesure de stabilite, et c'est la
    question que se pose un lecteur devant un classement d'editions.

    Ce que l'intervalle NE dit PAS
    ------------------------------
    Il ne garantit pas de contenir la valeur vraie dans 95 % des cas. Cette
    nuance n'est pas une precaution de style, elle vient d'un fait mesure sur
    le banc d'etalonnage : reechantillonner un support deja creux le creuse
    davantage, si bien que la distribution bootstrap de la JSD se situe
    systematiquement au-dessus du point estime. Un intervalle percentile brut
    ne contient alors meme pas sa propre estimation ponctuelle - resultat
    indefendable dans un rapport.

    Construction retenue
    --------------------
    La dispersion bootstrap est mesuree autour de la mediane des replications,
    puis transplantee sur le point estime :

        borne_basse = theta - (mediane* - quantile_bas*)
        borne_haute = theta + (quantile_haut* - mediane*)

    L'intervalle contient donc toujours l'estimation, et sa largeur est bien
    celle de la variabilite d'echantillonnage. Le deplacement residuel de
    l'estimateur par rapport a la valeur vraie est traite separement - par la
    correction de Miller-Madow, et borne par le controle de justesse du banc.
    """
    if config.bootstrap <= 0:
        return None
    n_a, n_b = int(round(sum(counts_a))), int(round(sum(counts_b)))
    if n_a <= 0 or n_b <= 0:
        return None

    p_a, p_b = _normalize(counts_a), _normalize(counts_b)
    rng = random.Random(config.seed)
    replicates: list[float] = []
    for _ in range(config.bootstrap):
        # Le meme estimateur que la mesure ponctuelle est applique a chaque
        # replication : un intervalle construit avec un autre estimateur que
        # celui qu'il est cense encadrer serait sans signification.
        replicates.append(
            jensen_shannon_corrected(
                _multinomial(rng, n_a, p_a), _multinomial(rng, n_b, p_b)
            )
        )

    replicates.sort()
    tail = (1.0 - config.level) / 2.0
    low_q = _percentile(replicates, tail)
    high_q = _percentile(replicates, 1.0 - tail)
    median_q = _percentile(replicates, 0.5)

    point = jensen_shannon_corrected(counts_a, counts_b)
    return Interval(
        lower=max(0.0, point - max(0.0, median_q - low_q)),
        upper=min(1.0, point + max(0.0, high_q - median_q)),
        level=config.level,
    )


def permutation_p_value(
    counts_a: Sequence[float],
    counts_b: Sequence[float],
    observed: float,
    config: UncertaintyConfig,
) -> tuple[float | None, float | None]:
    """Probabilite d'observer une divergence >= `observed` sous hypothese nulle.

    Hypothese nulle : les occurrences des deux editions proviennent d'une seule
    population, et leur repartition entre les deux editions est arbitraire.

    Test exact par permutation
    --------------------------
    Les occurrences des deux editions sont mises en commun, puis redistribuees
    au hasard en deux groupes conservant les effectifs reels n_a et n_b. Sous
    l'hypothese nulle, cette redistribution est equiprobable : la distribution
    des divergences ainsi obtenues est donc exactement la loi de la statistique
    sous H0, sans hypothese parametrique.

    Une version anterieure tirait les deux groupes dans la distribution mise en
    commun (bootstrap parametrique) plutot que de permuter les occurrences
    reelles. C'etait plus simple et sensiblement faux : le banc d'etalonnage a
    mesure un taux de faux positifs de 15,5 % pour un seuil nominal de 5 %,
    soit environ trois fois trop de divergences declarees significatives.
    Redistribuer les occurrences observees, au lieu de les re-tirer, supprime
    cette source d'erreur - le conditionnement aux effectifs marginaux reels
    est precisement ce qui rend le test exact.

    Renvoie (p-valeur, mediane de la distribution nulle). La mediane est le
    chiffre le plus parlant : elle donne la divergence « gratuite », celle que
    deux editions obtiendraient sans aucun ecart de cadrage.

    Le +1 au numerateur et au denominateur est la correction de Davison &
    Hinkley (1997) : elle interdit une p-valeur exactement nulle, qui
    surestimerait la certitude permise par un nombre fini de permutations.
    """
    if config.permutations <= 0:
        return None, None

    pooled = [a + b for a, b in zip(counts_a, counts_b)]
    n_a = int(round(sum(counts_a)))
    n_b = int(round(sum(counts_b)))
    if n_a <= 0 or n_b <= 0:
        return None, None

    # Materialisation des occurrences : une entree par occurrence, portant
    # l'indice de son concept.
    occurrences: list[int] = []
    for index, mass in enumerate(pooled):
        repeats = int(round(mass))
        if repeats > 0:
            occurrences.extend([index] * repeats)

    total = len(occurrences)
    if total < n_a + 1:
        return None, None
    # Les effectifs peuvent avoir ete arrondis ; on realigne sur ce qui existe.
    n_a = min(n_a, total - 1)

    rng = random.Random(config.seed + 1)
    width = len(pooled)
    null_draws: list[float] = []
    at_least_as_extreme = 0

    for _ in range(config.permutations):
        # Fisher-Yates partiel : seules les n_a premieres positions sont
        # tirees, ce qui suffit a obtenir un sous-ensemble uniforme et evite de
        # brasser inutilement la totalite des occurrences.
        for position in range(n_a):
            swap = rng.randrange(position, total)
            occurrences[position], occurrences[swap] = (
                occurrences[swap],
                occurrences[position],
            )

        sample_a = [0.0] * width
        for index in occurrences[:n_a]:
            sample_a[index] += 1.0
        # Le complement se deduit du total : inutile de reparcourir l'autre
        # groupe, qui est en general le plus grand des deux.
        sample_b = [pooled[i] - sample_a[i] for i in range(width)]

        value = jensen_shannon_corrected(sample_a, sample_b)
        null_draws.append(value)
        if value >= observed:
            at_least_as_extreme += 1

    null_draws.sort()
    p_value = (at_least_as_extreme + 1) / (config.permutations + 1)
    return p_value, _percentile(null_draws, 0.5)


# ---------------------------------------------------------------------------
# Matrice
# ---------------------------------------------------------------------------


def divergence_matrix(
    distributions: Sequence[ConceptDistribution],
    space: Sequence[str],
    config: UncertaintyConfig | None = None,
) -> DivergenceMatrix:
    """Matrice complete des divergences par paires, avec incertitude."""
    settings = config or UncertaintyConfig()
    if len(distributions) < 2:
        raise ConfigurationError("au moins deux editions sont necessaires")

    vectors = {
        d.lang: [d.probabilities.get(qid, 0.0) for qid in space] for d in distributions
    }
    # Les effectifs bruts, non lisses, pilotent l'inference : reechantillonner
    # une distribution lissee reviendrait a injecter le prior dans la mesure
    # d'incertitude et a resserrer artificiellement les intervalles.
    counts = {
        d.lang: [d.raw_counts.get(qid, 0.0) for qid in space] for d in distributions
    }

    langs = tuple(d.lang for d in distributions)
    pairs: list[DivergencePair] = []
    for i, lang_a in enumerate(langs):
        for lang_b in langs[i + 1 :]:
            p, q = vectors[lang_a], vectors[lang_b]
            # Mesure principale : estimateur corrige du biais, sur effectifs
            # bruts. Le lissage sert a decrire et a comparer, pas a estimer.
            observed = jensen_shannon_corrected(counts[lang_a], counts[lang_b])
            interval = bootstrap_interval(counts[lang_a], counts[lang_b], settings)
            p_value, null_median = permutation_p_value(
                counts[lang_a], counts[lang_b], observed, settings
            )
            pairs.append(
                DivergencePair(
                    lang_a=lang_a,
                    lang_b=lang_b,
                    jsd=observed,
                    hellinger=hellinger(p, q),
                    overlap=overlap(p, q),
                    interval=interval,
                    null_p_value=p_value,
                    null_median=null_median,
                )
            )

    return DivergenceMatrix(langs=langs, pairs=tuple(pairs))
