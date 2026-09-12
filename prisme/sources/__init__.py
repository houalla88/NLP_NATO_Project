"""Couche d'acquisition : tout ce qui touche au reseau ou au disque."""

from .base import DossierSource, HistorySource
from .local import (
    NATURES,
    SCHEMA_ID,
    LocalCorpusSource,
    dump_dossier,
    load_dossier,
    resolve_corpus_path,
)
from .mediawiki import MediaWikiSource, classify_section, parse_links

__all__ = [
    "NATURES", "SCHEMA_ID", "DossierSource", "HistorySource", "LocalCorpusSource",
    "MediaWikiSource", "classify_section", "dump_dossier", "load_dossier",
    "parse_links", "resolve_corpus_path",
]
