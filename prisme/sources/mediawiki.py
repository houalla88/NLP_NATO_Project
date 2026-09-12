"""Client MediaWiki / Wikidata.

Methode d'extraction
--------------------
Le texte d'un article n'est pas analyse comme du langage : il est analyse comme
un *graphe d'attention*. Chaque lien interne pointe vers une page, et cette page
porte un identifiant Wikidata identique dans toutes les langues. Compter les
liens d'un article revient donc a mesurer la repartition de son attention sur
un espace de concepts neutre linguistiquement.

Ce que cela evite : traduction automatique, lemmatisation, desambiguisation
lexicale, lexiques de sentiment - c'est-a-dire la totalite des composants qui,
dans une chaine NLP multilingue classique, sont a la fois les plus couteux, les
moins auditables, et les plus inegalement performants selon la langue. Un
lexique de sentiment russe et un lexique anglais n'ont ni la meme couverture ni
la meme calibration ; comparer leurs sorties revient a comparer deux instruments
non etalonnes.

Ce que cela coute : on ne mesure que ce qui est lie. Un theme traite en prose
sans lien interne est invisible. La mesure porte donc sur le cadrage
*structurel* de l'article, ce qui est un objet plus etroit mais nettement plus
objectivable que « la perception ».

Securite
--------
Le client ne prend jamais d'URL en entree. Il compose ses requetes a partir
d'un code de langue valide, verifie l'hote avant emission et apres redirection,
limite son debit, plafonne la taille des reponses et n'evalue aucun contenu
distant.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..config import HttpSettings, Settings, assert_allowed_host
from ..domain.errors import SourceError, SourceUnavailableError
from ..domain.models import (
    ArticleSnapshot,
    ConceptObservation,
    EntityDossier,
    Provenance,
    RevisionRecord,
    canonical_hash,
    utcnow,
    validate_lang,
    validate_qid,
)

# Lien interne en wikitexte : [[Cible]] ou [[Cible|Libelle affiche]].
_LINK_RE = re.compile(r"\[\[([^\[\]|<>{}]+?)(?:\|[^\[\]]*?)?\]\]")

# Titre de section : == Titre == a ====== Titre ======
_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)

# Prefixe d'interwiki ou de lien interlangue : "en:", "zh-yue:", "commons:".
_INTERWIKI_RE = re.compile(r"^[a-z][a-z0-9-]{1,11}:")

# Espaces de noms a exclure du comptage, par mot-cle canonique. Les alias
# localises sont recuperes en direct via siteinfo ; cette liste est le filet de
# securite si l'appel siteinfo echoue.
_FALLBACK_NAMESPACE_PREFIXES = {
    "file", "image", "category", "template", "help", "portal", "module",
    "wikipedia", "project", "mediawiki", "special", "talk", "media",
}

# Classification des sections vers les categories de ponderation structurelle.
# Volontairement incomplete : une section non reconnue recoit le poids neutre
# "body". Un dictionnaire de sections qui se voudrait exhaustif serait une
# source de biais silencieux des qu'une langue y serait moins bien couverte.
_SECTION_ALIASES: Mapping[str, str] = {
    # references
    "references": "references", "notes": "references", "sources": "references",
    "bibliography": "references", "footnotes": "references",
    "примечания": "references", "источники": "references", "литература": "references",
    "notes et references": "references", "bibliographie": "references",
    "einzelnachweise": "references", "literatur": "references",
    "przypisy": "references", "bibliografia": "references",
    "kaynakça": "references", "посилання": "references", "примітки": "references",
    # voir aussi
    "see also": "seealso", "external links": "seealso",
    "см. также": "seealso", "ссылки": "seealso",
    "voir aussi": "seealso", "liens externes": "seealso", "articles connexes": "seealso",
    "siehe auch": "seealso", "weblinks": "seealso",
    "zobacz też": "seealso", "linki zewnętrzne": "seealso",
    "ayrıca bakınız": "seealso", "dış bağlantılar": "seealso",
    "див. також": "seealso",
    # critique - singuliers ET pluriels : l'usage varie d'un article a l'autre
    # au sein d'une meme edition, et une forme manquante fait basculer la
    # section entiere sur le poids neutre sans qu'aucune erreur ne soit levee.
    "criticism": "criticism", "criticisms": "criticism",
    "controversy": "criticism", "controversies": "criticism",
    "critique": "criticism", "critiques": "criticism",
    "controverse": "criticism", "controverses": "criticism",
    "critiques et controverses": "criticism",
    "критика": "criticism", "критика и споры": "criticism",
    "kritik": "criticism", "kritiken": "criticism",
    "krytyka": "criticism", "kontrowersje": "criticism",
    "eleştiri": "criticism", "eleştiriler": "criticism",
}


class _RateLimiter:
    """Limiteur de debit a intervalle minimal garanti entre deux requetes."""

    def __init__(self, max_per_second: float) -> None:
        self._interval = 1.0 / max_per_second
        self._last = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last = time.monotonic()


class _HttpClient:
    """Transport JSON minimal : stdlib seule, durci, reessais bornes."""

    def __init__(self, settings: HttpSettings) -> None:
        self._settings = settings
        self._limiter = _RateLimiter(settings.max_requests_per_second)

    def get_json(self, host: str, params: Mapping[str, str]) -> dict[str, Any]:
        assert_allowed_host(host)
        query = urllib.parse.urlencode({**params, "format": "json"})
        url = f"https://{host}/w/api.php?{query}"

        last_error: Exception | None = None
        for attempt in range(self._settings.max_retries + 1):
            self._limiter.wait()
            try:
                return self._request(url)
            except SourceUnavailableError:
                # Refus definitif (4xx hors 429) : reessayer est inutile et
                # impoli envers le service.
                raise
            except Exception as exc:  # transport, 5xx, 429, JSON illisible
                last_error = exc
                if attempt >= self._settings.max_retries:
                    break
                # Recul exponentiel deterministe ; pas de jitter aleatoire afin
                # que deux executions identiques restent comparables en duree.
                time.sleep(self._settings.backoff_base_seconds * (2**attempt))

        raise SourceError(
            f"echec apres {self._settings.max_retries + 1} tentatives sur {host}: "
            f"{last_error}"
        ) from last_error

    def _request(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._settings.timeout_seconds
            ) as response:
                # Une redirection a pu deplacer la requete hors perimetre.
                assert_allowed_host(urllib.parse.urlparse(response.geturl()).hostname or "")
                payload = response.read(self._settings.max_response_bytes + 1)
                if len(payload) > self._settings.max_response_bytes:
                    raise SourceError(
                        f"reponse au-dela du plafond "
                        f"({self._settings.max_response_bytes} octets) : {url}"
                    )
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504):
                raise SourceError(f"HTTP {exc.code} sur {url}") from exc
            raise SourceUnavailableError(f"HTTP {exc.code} sur {url}") from exc
        except urllib.error.URLError as exc:
            raise SourceError(f"transport indisponible pour {url}: {exc.reason}") from exc

        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceError(f"reponse non-JSON depuis {url}") from exc

        if isinstance(decoded, dict) and "error" in decoded:
            detail = decoded["error"].get("info", "erreur API non detaillee")
            raise SourceUnavailableError(f"API MediaWiki : {detail}")
        if not isinstance(decoded, dict):
            raise SourceError(f"structure JSON inattendue depuis {url}")
        return decoded


# ---------------------------------------------------------------------------
# Analyse du wikitexte
# ---------------------------------------------------------------------------


def _normalize_heading(heading: str) -> str:
    """Forme canonique d'un titre de section, insensible aux diacritiques.

    « Notes et references », « Notes et références » et « NOTES ET RÉFÉRENCES »
    doivent tomber sur la meme entree. Sans cette normalisation, la table
    d'alias ne fonctionnerait que pour les langues sans signes diacritiques,
    ce qui introduirait un biais de ponderation structurelle purement
    orthographique - exactement le type de defaut qui passe inapercu et
    deplace ensuite tous les resultats.
    """
    decomposed = unicodedata.normalize("NFKD", heading.strip())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().rstrip(":：").strip()


# Table d'alias indexee sous forme canonique, construite une fois au chargement.
_SECTION_LOOKUP: dict[str, str] = {
    _normalize_heading(key): value for key, value in _SECTION_ALIASES.items()
}


def classify_section(heading: str) -> str:
    """Categorie de ponderation d'un titre de section, 'body' par defaut."""
    return _SECTION_LOOKUP.get(_normalize_heading(heading), "body")


def parse_links(
    wikitext: str, excluded_prefixes: Iterable[str]
) -> list[tuple[str, str]]:
    """Liens internes d'un article, avec la section ou ils apparaissent.

    Renvoie une liste de (titre cible, categorie de section). Le texte precedant
    le premier titre de section est classe 'lead'.

    Sont ecartes : fichiers, categories, modeles et autres espaces de noms
    techniques ; les liens interlangue et interwiki ; les ancres internes. Ces
    exclusions ne sont pas cosmetiques - une categorie ou un modele apparait
    dans toutes les pages d'un domaine et noierait le signal de cadrage.
    """
    excluded = {p.lower() for p in excluded_prefixes}
    sections: list[tuple[int, str]] = [(0, "lead")]
    for match in _HEADING_RE.finditer(wikitext):
        sections.append((match.start(), classify_section(match.group(2))))

    def section_at(position: int) -> str:
        current = "lead"
        for start, name in sections:
            if start <= position:
                current = name
            else:
                break
        return current

    results: list[tuple[str, str]] = []
    for match in _LINK_RE.finditer(wikitext):
        target = match.group(1).strip()
        if not target or target.startswith(("#", ":")):
            continue
        target = target.split("#", 1)[0].strip()
        if not target:
            continue
        if ":" in target:
            prefix = target.split(":", 1)[0].strip().lower()
            if prefix in excluded or _INTERWIKI_RE.match(target.lower()):
                continue
        # Normalisation MediaWiki : underscore equivaut a espace, premiere
        # lettre insensible a la casse.
        normalized = target.replace("_", " ").strip()
        if not normalized:
            continue
        normalized = normalized[0].upper() + normalized[1:]
        results.append((normalized, section_at(match.start())))

    return results


def _parse_timestamp(raw: str) -> datetime:
    """Horodatage ISO-8601 MediaWiki vers datetime conscient du fuseau."""
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


class MediaWikiSource:
    """Acquisition en direct depuis Wikipedia et Wikidata.

    Le point d'entree est un QID Wikidata, jamais un titre : c'est ce qui
    garantit que les articles compares decrivent bien le meme referent et non
    deux sujets homonymes. Les titres sont resolus par les liens de site
    Wikidata.
    """

    source_id = "mediawiki-live"

    # Limite anonyme de l'API MediaWiki pour les requetes multi-titres.
    _TITLE_BATCH = 50

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings.from_env()
        self._http = _HttpClient(self._settings.http)
        self._namespace_cache: dict[str, set[str]] = {}

    # -- resolution ---------------------------------------------------------

    def sitelinks(self, entity_qid: str) -> dict[str, str]:
        """Titre de l'article par edition linguistique, depuis Wikidata."""
        qid = validate_qid(entity_qid)
        payload = self._http.get_json(
            "www.wikidata.org",
            {"action": "wbgetentities", "ids": qid, "props": "sitelinks|labels"},
        )
        entity = payload.get("entities", {}).get(qid)
        if not entity:
            raise SourceUnavailableError(f"entite Wikidata introuvable : {qid}")

        mapping: dict[str, str] = {}
        for wiki, link in (entity.get("sitelinks") or {}).items():
            if not wiki.endswith("wiki") or "wikiquote" in wiki or "wikinews" in wiki:
                continue
            lang = wiki[:-4].replace("_", "-")
            try:
                mapping[validate_lang(lang)] = link["title"]
            except Exception:
                # Un site hors schema linguistique (commonswiki, specieswiki)
                # n'est pas une edition comparable : on l'ignore sans echouer.
                continue
        return mapping

    def entity_label(self, entity_qid: str, preferred: Sequence[str] = ("fr", "en")) -> str:
        qid = validate_qid(entity_qid)
        payload = self._http.get_json(
            "www.wikidata.org", {"action": "wbgetentities", "ids": qid, "props": "labels"}
        )
        labels = (payload.get("entities", {}).get(qid) or {}).get("labels") or {}
        for lang in preferred:
            if lang in labels:
                return labels[lang]["value"]
        return next(iter(labels.values()), {}).get("value", qid) if labels else qid

    def _excluded_prefixes(self, lang: str) -> set[str]:
        """Alias d'espaces de noms a exclure, dans la langue de l'edition.

        Recuperes en direct : en russe, "Файл:" et "Категория:" ne
        ressemblent en rien a leurs equivalents anglais, et les coder en dur
        reviendrait a ne filtrer correctement que les editions latines.
        """
        if lang in self._namespace_cache:
            return self._namespace_cache[lang]

        prefixes = set(_FALLBACK_NAMESPACE_PREFIXES)
        try:
            payload = self._http.get_json(
                f"{lang}.wikipedia.org",
                {"action": "query", "meta": "siteinfo", "siprop": "namespaces|namespacealiases"},
            )
            for namespace in (payload.get("query", {}).get("namespaces") or {}).values():
                # L'espace 0 est l'espace principal : c'est precisement celui
                # que l'on veut conserver.
                if namespace.get("id", 0) == 0:
                    continue
                for key in ("*", "canonical"):
                    value = namespace.get(key)
                    if value:
                        prefixes.add(str(value).lower())
            for alias in payload.get("query", {}).get("namespacealiases") or []:
                if alias.get("id", 0) != 0 and alias.get("*"):
                    prefixes.add(str(alias["*"]).lower())
        except Exception:
            # Degradation explicite : le filtre de secours reste actif et le
            # rapport porte l'avertissement plutot que d'echouer l'analyse.
            pass

        self._namespace_cache[lang] = prefixes
        return prefixes

    # -- contenu ------------------------------------------------------------

    def _current_revision(self, lang: str, title: str) -> dict[str, Any]:
        payload = self._http.get_json(
            f"{lang}.wikipedia.org",
            {
                "action": "query", "prop": "revisions", "titles": title,
                "rvprop": "ids|timestamp|sha1|size|content", "rvslots": "main",
                "rvlimit": "1", "formatversion": "2", "redirects": "1",
            },
        )
        pages = payload.get("query", {}).get("pages") or []
        if not pages or pages[0].get("missing"):
            raise SourceUnavailableError(f"{lang}: article absent - {title!r}")
        revisions = pages[0].get("revisions") or []
        if not revisions:
            raise SourceUnavailableError(f"{lang}: aucune revision pour {title!r}")
        revision = revisions[0]
        revision["_title"] = pages[0].get("title", title)
        return revision

    def _resolve_qids(self, lang: str, titles: Sequence[str]) -> dict[str, str]:
        """Titre d'article -> QID Wikidata, par lots.

        Les tables `normalized` et `redirects` renvoyees par l'API sont suivies
        pour que le QID soit rattache au titre tel qu'il apparait dans le
        wikitexte, et non au titre canonique. Sans cela, tous les liens passant
        par une redirection seraient perdus.
        """
        resolved: dict[str, str] = {}
        unique = sorted(set(titles))

        for start in range(0, len(unique), self._TITLE_BATCH):
            batch = unique[start : start + self._TITLE_BATCH]
            payload = self._http.get_json(
                f"{lang}.wikipedia.org",
                {
                    "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                    "titles": "|".join(batch), "formatversion": "2", "redirects": "1",
                },
            )
            query = payload.get("query", {})
            alias: dict[str, str] = {}
            for table in ("normalized", "redirects"):
                for entry in query.get(table) or []:
                    alias[entry["from"]] = entry["to"]

            final_to_qid: dict[str, str] = {}
            for page in query.get("pages") or []:
                qid = (page.get("pageprops") or {}).get("wikibase_item")
                if qid:
                    final_to_qid[page.get("title", "")] = qid

            for original in batch:
                final = original
                # Une redirection peut en chainer une autre ; la boucle est
                # bornee pour ne pas tourner sur un cycle de redirection.
                for _ in range(4):
                    if final in alias:
                        final = alias[final]
                    else:
                        break
                if final in final_to_qid:
                    resolved[original] = final_to_qid[final]

        return resolved

    def revisions(self, lang: str, title: str, limit: int = 500) -> list[RevisionRecord]:
        """Historique de revisions, du plus ancien au plus recent."""
        collected: list[RevisionRecord] = []
        continuation: dict[str, str] = {}

        while len(collected) < limit:
            params = {
                "action": "query", "prop": "revisions", "titles": title,
                "rvprop": "ids|timestamp|sha1|size|user|flags",
                "rvlimit": str(min(500, limit - len(collected))),
                "formatversion": "2", "redirects": "1",
            }
            params.update(continuation)
            payload = self._http.get_json(f"{lang}.wikipedia.org", params)
            pages = payload.get("query", {}).get("pages") or []
            if not pages:
                break
            for revision in pages[0].get("revisions") or []:
                collected.append(
                    RevisionRecord(
                        rev_id=int(revision.get("revid", 0)),
                        timestamp=_parse_timestamp(revision["timestamp"]),
                        sha1=str(revision.get("sha1", "")),
                        size=int(revision.get("size", 0)),
                        editor=str(revision.get("user", "")),
                        is_anonymous=bool(revision.get("anon", False)),
                        is_minor=bool(revision.get("minor", False)),
                        parent_id=revision.get("parentid"),
                    )
                )
            cont = payload.get("continue")
            if not cont:
                break
            continuation = {k: v for k, v in cont.items() if k != "continue"}

        collected.sort(key=lambda r: r.timestamp)
        return collected

    # -- interface ----------------------------------------------------------

    def fetch(
        self,
        entity_qid: str,
        langs: Sequence[str],
        revision_limit: int = 500,
    ) -> EntityDossier:
        """Dossier complet de l'entite pour les langues demandees.

        Une edition manquante ou inaccessible n'interrompt pas la collecte :
        elle est absente du dossier. Le pipeline signale ensuite l'ecart entre
        langues demandees et langues obtenues, de sorte qu'une couverture
        partielle soit visible dans le rapport plutot que subie.
        """
        qid = validate_qid(entity_qid)
        wanted = [validate_lang(l) for l in langs]
        titles = self.sitelinks(qid)
        label = self.entity_label(qid)

        snapshots: list[ArticleSnapshot] = []
        concept_labels: dict[str, str] = {}

        for lang in wanted:
            title = titles.get(lang)
            if not title:
                continue
            try:
                revision = self._current_revision(lang, title)
                wikitext = (revision.get("slots", {}).get("main", {}) or {}).get("content", "")
                links = parse_links(wikitext, self._excluded_prefixes(lang))
                qid_by_title = self._resolve_qids(lang, [t for t, _ in links])

                counter: dict[tuple[str, str], int] = {}
                for link_title, section in links:
                    linked_qid = qid_by_title.get(link_title)
                    if not linked_qid or linked_qid == qid:
                        continue
                    counter[(linked_qid, section)] = counter.get((linked_qid, section), 0) + 1
                    concept_labels.setdefault(linked_qid, link_title)

                observations = tuple(
                    ConceptObservation(qid=k[0], count=v, section=k[1])
                    for k, v in sorted(counter.items())
                )
                history = self.revisions(lang, title, revision_limit)

                snapshots.append(
                    ArticleSnapshot(
                        lang=lang,
                        title=revision.get("_title", title),
                        entity_qid=qid,
                        revision_id=int(revision.get("revid", 0)),
                        revision_timestamp=_parse_timestamp(revision["timestamp"]),
                        revision_sha1=str(revision.get("sha1", "")),
                        byte_size=int(revision.get("size", 0)),
                        concepts=observations,
                        revisions=tuple(history),
                        provenance=Provenance(
                            source_id=self.source_id,
                            retrieved_at=utcnow(),
                            endpoint=f"https://{lang}.wikipedia.org/w/api.php",
                            payload_hash=canonical_hash(
                                {"revid": revision.get("revid"), "sha1": revision.get("sha1")}
                            ),
                        ),
                    )
                )
            except SourceUnavailableError:
                continue

        if not snapshots:
            raise SourceUnavailableError(
                f"aucune edition exploitable pour {qid} parmi {list(wanted)}"
            )

        return EntityDossier(
            entity_qid=qid,
            label=label,
            snapshots=tuple(snapshots),
            concept_labels=concept_labels,
            corpus_id=f"live:{qid}:{utcnow().date().isoformat()}",
        )
