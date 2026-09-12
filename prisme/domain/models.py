"""Modele de domaine : immuable, sans I/O, sans dependance.

Regle de couche : ce module ne connait ni le reseau, ni le disque, ni Flask.
Il definit *ce qui est mesure*, pas *comment on l'obtient*. Toutes les
structures sont figees (`frozen=True`) afin qu'un resultat ne puisse pas
etre mute apres avoir ete date et hache.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .errors import ConfigurationError

# Codes d'edition linguistique Wikipedia : 2 a 3 lettres, eventuellement
# suivies d'un variant (ex. "zh-yue", "be-tarask"). Valide en entree de la
# couche source : une langue non validee se retrouverait concatenee dans un
# nom d'hote (ssrf) ou dans un chemin de fichier (traversee).
_LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")

# Identifiant Wikidata : Q suivi de chiffres, sans zero initial.
_QID_RE = re.compile(r"^Q[1-9][0-9]*$")


def validate_lang(code: str) -> str:
    """Valide un code d'edition linguistique et le renvoie normalise."""
    if not isinstance(code, str):
        raise ConfigurationError(f"code de langue non textuel : {code!r}")
    normalized = code.strip().lower()
    if not _LANG_RE.match(normalized):
        raise ConfigurationError(
            f"code de langue invalide : {code!r} "
            "(attendu : 2-3 lettres, variant optionnel, ex. 'ru', 'zh-yue')"
        )
    return normalized


def validate_qid(qid: str) -> str:
    """Valide un identifiant Wikidata et le renvoie normalise."""
    if not isinstance(qid, str):
        raise ConfigurationError(f"QID non textuel : {qid!r}")
    normalized = qid.strip().upper()
    if not _QID_RE.match(normalized):
        raise ConfigurationError(f"QID Wikidata invalide : {qid!r} (attendu 'Q7184')")
    return normalized


def utcnow() -> datetime:
    """Horodatage UTC conscient du fuseau. Jamais de naive datetime."""
    return datetime.now(timezone.utc)


def canonical_hash(payload: Any) -> str:
    """Empreinte SHA-256 d'une structure, stable a la serialisation.

    Utilisee pour l'audit : deux executions produisant le meme contenu
    produisent la meme empreinte, independamment de l'ordre des cles.
    """
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConceptObservation:
    """Une occurrence de concept dans un article, projetee en espace neutre.

    Le point cle de la methode : un lien interne d'article pointe vers une
    autre page, et cette page porte un identifiant Wikidata (`qid`) qui est
    le *meme* quelle que soit la langue. Compter des QID plutot que des mots
    rend deux articles de langues differentes directement comparables, sans
    traduction automatique et sans modele de langue dans la boucle.

    `weight` porte la ponderation structurelle (voir `SectionWeighting`) :
    un concept cite dans le chapeau introductif ne pese pas comme un concept
    enterre en section « Voir aussi ».
    """

    qid: str
    count: int
    weight: float = 1.0
    label: str = ""
    section: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "qid", validate_qid(self.qid))
        if self.count < 0:
            raise ConfigurationError(f"count negatif pour {self.qid}: {self.count}")
        if self.weight < 0:
            raise ConfigurationError(f"weight negatif pour {self.qid}: {self.weight}")

    @property
    def mass(self) -> float:
        """Masse d'attention effective : occurrences x ponderation."""
        return self.count * self.weight


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """Une revision d'article, telle que l'expose l'API MediaWiki.

    `sha1` est l'empreinte du *contenu* de la revision fournie par MediaWiki.
    C'est elle qui permet la detection de retour arriere par identite
    (cf. `prisme.metrics.contestedness`) : si une revision reproduit
    exactement l'empreinte d'une revision anterieure, l'etat du texte a ete
    restaure, ce qui est la definition operationnelle d'un revert.
    """

    rev_id: int
    timestamp: datetime
    sha1: str
    size: int
    editor: str = ""
    is_anonymous: bool = False
    is_minor: bool = False
    parent_id: int | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ConfigurationError(
                f"revision {self.rev_id}: horodatage sans fuseau horaire"
            )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Tracabilite d'un instantane : d'ou il vient, quand, et sous quelle forme.

    Sans ce bloc, un resultat de divergence n'est pas auditable : on ne peut
    pas rejouer la mesure ni prouver sur quel etat du texte elle a porte.
    """

    source_id: str
    retrieved_at: datetime
    endpoint: str = ""
    payload_hash: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ConfigurationError("provenance: retrieved_at sans fuseau horaire")


@dataclass(frozen=True, slots=True)
class ArticleSnapshot:
    """Etat fige d'un article, dans une langue, a une revision precise."""

    lang: str
    title: str
    entity_qid: str
    revision_id: int
    revision_timestamp: datetime
    concepts: tuple[ConceptObservation, ...]
    provenance: Provenance
    revision_sha1: str = ""
    byte_size: int = 0
    revisions: tuple[RevisionRecord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lang", validate_lang(self.lang))
        object.__setattr__(self, "entity_qid", validate_qid(self.entity_qid))
        if not self.title.strip():
            raise ConfigurationError(f"snapshot {self.lang}: titre vide")

    @property
    def total_mass(self) -> float:
        return sum(c.mass for c in self.concepts)

    @property
    def support(self) -> int:
        """Nombre de concepts distincts observes."""
        return len({c.qid for c in self.concepts})

    def audit_fingerprint(self) -> str:
        """Empreinte reproductible de l'instantane, hors horodatage de collecte."""
        return canonical_hash(
            {
                "lang": self.lang,
                "title": self.title,
                "entity_qid": self.entity_qid,
                "revision_id": self.revision_id,
                "revision_sha1": self.revision_sha1,
                "concepts": sorted(
                    (c.qid, c.count, round(c.weight, 6)) for c in self.concepts
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class EntityDossier:
    """Ensemble des instantanes d'une meme entite, toutes langues confondues.

    C'est l'unite d'analyse : on ne compare jamais deux articles au hasard,
    on compare les descriptions d'un *meme referent*, identifie par son QID.
    """

    entity_qid: str
    label: str
    snapshots: tuple[ArticleSnapshot, ...]
    concept_labels: Mapping[str, str] = field(default_factory=dict)
    collected_at: datetime = field(default_factory=utcnow)
    corpus_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_qid", validate_qid(self.entity_qid))
        langs = [s.lang for s in self.snapshots]
        duplicates = {l for l in langs if langs.count(l) > 1}
        if duplicates:
            raise ConfigurationError(
                f"dossier {self.entity_qid}: langues dupliquees {sorted(duplicates)}"
            )
        for snapshot in self.snapshots:
            if snapshot.entity_qid != self.entity_qid:
                raise ConfigurationError(
                    f"snapshot {snapshot.lang} porte l'entite {snapshot.entity_qid}, "
                    f"attendu {self.entity_qid}"
                )

    @property
    def langs(self) -> tuple[str, ...]:
        return tuple(s.lang for s in self.snapshots)

    def by_lang(self, lang: str) -> ArticleSnapshot:
        target = validate_lang(lang)
        for snapshot in self.snapshots:
            if snapshot.lang == target:
                return snapshot
        raise KeyError(f"aucun instantane pour la langue {target!r}")

    def label_for(self, qid: str) -> str:
        """Libelle lisible d'un concept, ou le QID a defaut.

        Le libelle est cosmetique : aucune metrique ne depend de lui, ce qui
        garantit qu'un etiquetage manquant ou approximatif dans une langue
        ne deplace jamais un resultat chiffre.
        """
        return self.concept_labels.get(qid) or qid

    def audit_fingerprint(self) -> str:
        return canonical_hash(
            {
                "entity_qid": self.entity_qid,
                "snapshots": sorted(s.audit_fingerprint() for s in self.snapshots),
            }
        )


# ---------------------------------------------------------------------------
# Resultats de mesure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConceptDistribution:
    """Distribution de probabilite sur l'espace conceptuel, pour une langue."""

    lang: str
    probabilities: Mapping[str, float]
    raw_counts: Mapping[str, float]
    total_mass: float
    smoothing: str = "none"

    @property
    def support(self) -> int:
        return len(self.probabilities)

    def entropy_bits(self) -> float:
        """Entropie de Shannon en bits : concentration de l'attention.

        Une entropie basse signale un article qui concentre son attention sur
        peu de concepts ; une entropie haute, une couverture dispersee. Lue
        seule elle ne dit rien d'un biais, elle decrit une forme.
        """
        from math import log2

        return -sum(p * log2(p) for p in self.probabilities.values() if p > 0)


@dataclass(frozen=True, slots=True)
class Interval:
    """Intervalle de confiance par percentiles bootstrap."""

    lower: float
    upper: float
    level: float = 0.95

    @property
    def width(self) -> float:
        return self.upper - self.lower


@dataclass(frozen=True, slots=True)
class DivergencePair:
    """Divergence mesuree entre deux editions, avec son incertitude.

    Un point de divergence sans intervalle n'est pas exploitable : sur des
    articles courts, la JSD entre deux tirages d'une *meme* distribution est
    deja nettement superieure a zero. C'est la comparaison a `null_p_value`
    qui separe un ecart de cadrage d'un artefact d'echantillonnage.
    """

    lang_a: str
    lang_b: str
    jsd: float
    hellinger: float
    overlap: float
    interval: Interval | None = None
    null_p_value: float | None = None
    null_median: float | None = None

    @property
    def is_significant(self) -> bool:
        """Vrai si la divergence depasse le bruit d'echantillonnage a 5 %."""
        return self.null_p_value is not None and self.null_p_value < 0.05


@dataclass(frozen=True, slots=True)
class DivergenceMatrix:
    """Matrice symetrique de divergence entre toutes les paires d'editions."""

    langs: tuple[str, ...]
    pairs: tuple[DivergencePair, ...]

    def get(self, lang_a: str, lang_b: str) -> DivergencePair:
        for pair in self.pairs:
            if {pair.lang_a, pair.lang_b} == {lang_a, lang_b}:
                return pair
        raise KeyError(f"paire absente : {lang_a}/{lang_b}")

    def as_grid(self) -> list[list[float]]:
        """Matrice carree de JSD, diagonale nulle."""
        index = {lang: i for i, lang in enumerate(self.langs)}
        grid = [[0.0] * len(self.langs) for _ in self.langs]
        for pair in self.pairs:
            i, j = index[pair.lang_a], index[pair.lang_b]
            grid[i][j] = grid[j][i] = pair.jsd
        return grid

    def mean_divergence(self, lang: str) -> float:
        """Divergence moyenne d'une edition a toutes les autres.

        Sert d'indicateur d'isolement : l'edition la plus eloignee de la
        moyenne des autres est celle dont le cadrage est le plus singulier.
        """
        values = [p.jsd for p in self.pairs if lang in (p.lang_a, p.lang_b)]
        if not values:
            raise KeyError(f"langue absente de la matrice : {lang!r}")
        return sum(values) / len(values)


@dataclass(frozen=True, slots=True)
class DistinctiveConcept:
    """Concept sur-represente dans une edition, avec son score de confiance.

    `z_score` provient de la methode log-odds a prior de Dirichlet informatif
    (Monroe, Colaresi & Quinn, 2008). Elle est preferee a une simple
    difference de frequences parce qu'elle regularise les concepts rares :
    sans elle, tout concept cite une seule fois dans une seule edition
    remonte en tete du classement, ce qui est un artefact, pas un signal.
    """

    qid: str
    label: str
    lang: str
    z_score: float
    log_odds: float
    count_in: float
    count_out: float
    share_in: float
    share_out: float

    @property
    def direction(self) -> str:
        return "sur-represente" if self.z_score > 0 else "sous-represente"


@dataclass(frozen=True, slots=True)
class SilenceFinding:
    """Concept present ailleurs et absent ici.

    L'absence est une decision editoriale mesurable au meme titre que la
    presence. On ne retient que les concepts suffisamment installes dans les
    autres editions pour que leur absence ne soit pas un simple hasard de
    redaction.
    """

    qid: str
    label: str
    absent_in: str
    present_in: tuple[str, ...]
    mean_share_elsewhere: float


@dataclass(frozen=True, slots=True)
class ContestednessProfile:
    """Intensite du conflit editorial sur une edition donnee.

    Ces indicateurs decrivent la *stabilite* d'un texte, pas sa veracite :
    un article tres contesté n'est pas un article faux, c'est un article dont
    la formulation ne fait pas consensus entre ses contributeurs.
    """

    lang: str
    n_revisions: int
    window_days: float
    identity_reverts: int
    revert_rate: float
    mutual_revert_index: float
    distinct_editors: int
    anonymous_share: float
    ewma_intensity: float
    intensity_series: tuple[tuple[datetime, float], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DriftPoint:
    """Ecart d'une edition a son propre etat de reference, a une date donnee."""

    lang: str
    at: datetime
    revision_id: int
    jsd_vs_baseline: float
    support: int


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Bundle de resultats complet, autoportant et auditable.

    Contient tout ce qu'il faut pour rejouer et contester la mesure :
    empreinte du corpus d'entree, version de la methode, parametres effectifs
    et avertissements emis pendant le calcul.
    """

    entity_qid: str
    entity_label: str
    corpus_id: str
    method_version: str
    generated_at: datetime
    langs: tuple[str, ...]
    distributions: tuple[ConceptDistribution, ...]
    divergence: DivergenceMatrix
    distinctive: tuple[DistinctiveConcept, ...]
    silences: tuple[SilenceFinding, ...]
    contestedness: tuple[ContestednessProfile, ...]
    drift: tuple[DriftPoint, ...]
    embedding: Mapping[str, tuple[float, float]]
    parameters: Mapping[str, Any]
    input_fingerprint: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    data_nature: str = "unknown"

    def distinctive_for(self, lang: str, limit: int = 10) -> list[DistinctiveConcept]:
        ranked = [d for d in self.distinctive if d.lang == lang and d.z_score > 0]
        ranked.sort(key=lambda d: d.z_score, reverse=True)
        return ranked[:limit]

    def most_isolated_lang(self) -> str:
        """Edition dont le cadrage s'ecarte le plus de l'ensemble."""
        return max(self.langs, key=self.divergence.mean_divergence)


def to_jsonable(value: Any) -> Any:
    """Serialise recursivement un objet du domaine en structures JSON pures."""
    if hasattr(value, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
