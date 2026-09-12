"""Source corpus local : instantanes figes sur disque.

Deux usages, un seul format :

1. Rejouabilite. Un corpus collecte en direct est serialise puis reanalyse des
   mois plus tard a l'identique, alors meme que les articles ont change. Sans
   cela, aucun resultat publie n'est verifiable - c'est la condition minimale
   pour qu'une mesure sur Wikipedia soit opposable.
2. Etalonnage. Un corpus synthetique a divergence connue permet de verifier que
   les metriques restituent ce qu'on y a injecte (cf. `prisme.calibration`).

Le champ `nature` distingue explicitement les deux. Il est repris tel quel dans
le rapport et dans l'interface : aucun chiffre issu d'un corpus synthetique ne
peut etre presente comme une observation empirique.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..domain.errors import CorpusError
from ..domain.models import (
    ArticleSnapshot,
    ConceptObservation,
    EntityDossier,
    Provenance,
    RevisionRecord,
    canonical_hash,
    utcnow,
    validate_lang,
)

SCHEMA_ID = "prisme-corpus/1"

# Valeurs autorisees pour `nature`. Toute autre valeur est refusee au
# chargement : un corpus dont la nature n'est pas declaree ne doit pas pouvoir
# produire un rapport, car rien n'y indiquerait qu'il est synthetique.
NATURES = {
    "recorded-live": "Instantane fige d'une collecte reelle sur l'API Wikimedia.",
    "synthetic-validation": "Corpus genere, a structure connue. Aucune valeur empirique.",
    "synthetic-demo": "Corpus genere a des fins de demonstration. Aucune valeur empirique.",
}


def _parse_dt(raw: Any, field: str) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CorpusError(f"{field}: horodatage illisible {raw!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolve_corpus_path(name: str, root: str | os.PathLike[str]) -> Path:
    """Resout un nom de corpus a l'interieur de `root`, sans evasion possible.

    Le nom vient potentiellement d'une requete HTTP (interface web). Le
    controle porte sur le chemin *resolu*, pas sur la chaine d'entree : c'est
    la seule verification qui resiste aux encodages et aux liens symboliques.
    """
    if not name or any(sep in name for sep in ("/", "\\", "\x00")) or name.startswith("."):
        raise CorpusError(f"nom de corpus invalide : {name!r}")

    base = Path(root).resolve()
    candidate = (base / f"{name}.json").resolve()
    if not candidate.is_relative_to(base):
        raise CorpusError(f"chemin de corpus hors perimetre : {name!r}")
    if not candidate.is_file():
        raise CorpusError(f"corpus introuvable : {name!r}")
    return candidate


def load_dossier(path: str | os.PathLike[str]) -> EntityDossier:
    """Charge et valide un corpus au format `prisme-corpus/1`."""
    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CorpusError(f"corpus introuvable : {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise CorpusError(f"corpus JSON invalide ({file_path}) : {exc}") from exc

    if raw.get("schema") != SCHEMA_ID:
        raise CorpusError(f"schema attendu {SCHEMA_ID!r}, trouve {raw.get('schema')!r}")

    nature = raw.get("nature")
    if nature not in NATURES:
        raise CorpusError(
            f"nature de corpus non declaree ou inconnue : {nature!r}. "
            f"Valeurs admises : {sorted(NATURES)}"
        )

    entity = raw.get("entity") or {}
    editions = raw.get("editions") or []
    if not editions:
        raise CorpusError("corpus sans edition")

    snapshots: list[ArticleSnapshot] = []
    for edition in editions:
        lang = validate_lang(edition.get("lang", ""))
        concepts = tuple(
            ConceptObservation(
                qid=item["qid"],
                count=int(item.get("count", 0)),
                weight=float(item.get("weight", 1.0)),
                label=str(item.get("label", "")),
                section=str(item.get("section", "")),
            )
            for item in edition.get("concepts") or []
        )
        revisions = tuple(
            RevisionRecord(
                rev_id=int(item.get("rev_id", 0)),
                timestamp=_parse_dt(item.get("timestamp"), f"{lang}.revisions.timestamp"),
                sha1=str(item.get("sha1", "")),
                size=int(item.get("size", 0)),
                editor=str(item.get("editor", "")),
                is_anonymous=bool(item.get("is_anonymous", False)),
                is_minor=bool(item.get("is_minor", False)),
                parent_id=item.get("parent_id"),
            )
            for item in edition.get("revisions") or []
        )
        snapshots.append(
            ArticleSnapshot(
                lang=lang,
                title=str(edition.get("title") or lang),
                entity_qid=entity.get("qid", ""),
                revision_id=int(edition.get("revision_id", 0)),
                revision_timestamp=_parse_dt(
                    edition.get("revision_timestamp") or "1970-01-01T00:00:00Z",
                    f"{lang}.revision_timestamp",
                ),
                revision_sha1=str(edition.get("revision_sha1", "")),
                byte_size=int(edition.get("byte_size", 0)),
                concepts=concepts,
                revisions=revisions,
                provenance=Provenance(
                    source_id=f"local:{nature}",
                    retrieved_at=_parse_dt(
                        raw.get("collected_at") or "1970-01-01T00:00:00Z", "collected_at"
                    ),
                    endpoint=str(file_path),
                    payload_hash=canonical_hash(edition),
                    notes=NATURES[nature],
                ),
            )
        )

    return EntityDossier(
        entity_qid=entity.get("qid", ""),
        label=str(entity.get("label") or entity.get("qid", "")),
        snapshots=tuple(snapshots),
        concept_labels=dict(raw.get("concept_labels") or {}),
        collected_at=_parse_dt(raw.get("collected_at") or utcnow(), "collected_at"),
        corpus_id=str(raw.get("corpus_id") or file_path.stem),
    )


def dump_dossier(dossier: EntityDossier, nature: str, path: str | os.PathLike[str]) -> Path:
    """Serialise un dossier au format corpus. Fige une collecte pour rejeu."""
    if nature not in NATURES:
        raise CorpusError(f"nature inconnue : {nature!r}")

    payload = {
        "schema": SCHEMA_ID,
        "corpus_id": dossier.corpus_id or dossier.entity_qid,
        "nature": nature,
        "collected_at": dossier.collected_at.astimezone(timezone.utc).isoformat(),
        "entity": {"qid": dossier.entity_qid, "label": dossier.label},
        "concept_labels": dict(dossier.concept_labels),
        "editions": [
            {
                "lang": s.lang,
                "title": s.title,
                "revision_id": s.revision_id,
                "revision_timestamp": s.revision_timestamp.astimezone(timezone.utc).isoformat(),
                "revision_sha1": s.revision_sha1,
                "byte_size": s.byte_size,
                "concepts": [
                    {"qid": c.qid, "count": c.count, "weight": c.weight, "section": c.section}
                    for c in s.concepts
                ],
                "revisions": [
                    {
                        "rev_id": r.rev_id,
                        "timestamp": r.timestamp.astimezone(timezone.utc).isoformat(),
                        "sha1": r.sha1,
                        "size": r.size,
                        "editor": r.editor,
                        "is_anonymous": r.is_anonymous,
                        "is_minor": r.is_minor,
                    }
                    for r in s.revisions
                ],
            }
            for s in dossier.snapshots
        ],
    }

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return target


class LocalCorpusSource:
    """Source lisant un corpus fige. Interchangeable avec `MediaWikiSource`."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self.source_id = f"local:{self._path.stem}"

    def fetch(self, entity_qid: str, langs: Sequence[str]) -> EntityDossier:
        dossier = load_dossier(self._path)
        if entity_qid and dossier.entity_qid != entity_qid:
            raise CorpusError(
                f"corpus {self._path.name} porte {dossier.entity_qid}, "
                f"entite demandee {entity_qid}"
            )
        if not langs:
            return dossier
        wanted = {validate_lang(l) for l in langs}
        kept = tuple(s for s in dossier.snapshots if s.lang in wanted)
        if not kept:
            raise CorpusError(f"aucune edition demandee dans {self._path.name}")
        return EntityDossier(
            entity_qid=dossier.entity_qid,
            label=dossier.label,
            snapshots=kept,
            concept_labels=dossier.concept_labels,
            collected_at=dossier.collected_at,
            corpus_id=dossier.corpus_id,
        )
