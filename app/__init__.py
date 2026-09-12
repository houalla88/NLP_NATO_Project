"""Interface web PRISME.

Portee volontairement etroite : l'application EXPOSE des rapports, elle n'en
declenche pas la collecte. Aucune route ne provoque d'appel reseau sortant,
aucune n'accepte de contenu utilisateur autre qu'un nom de corpus valide contre
une liste fermee. La surface d'attaque se reduit ainsi a la lecture de fichiers
dans un repertoire connu.

Ce choix n'est pas une limitation : une collecte Wikimedia prend plusieurs
minutes et doit rester tracee dans un corpus fige. La lancer depuis une requete
HTTP produirait des rapports non reproductibles et un point de deni de service.
Elle appartient a la CLI (`prisme collect`), pas au web.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request

from prisme import METHOD_VERSION, __version__
from prisme.domain.errors import PrismeError
from prisme.pipeline import AnalysisConfig, analyse
from prisme.metrics.divergence import UncertaintyConfig
from prisme.reporting import render_fragment, to_payload
from prisme.sources.local import load_dossier, resolve_corpus_path

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpora"

# Politique de securite du contenu. La page generee n'utilise ni script, ni
# ressource distante : la politique peut donc etre maximalement restrictive.
# 'unsafe-inline' est accorde aux seuls styles, que le rendu injecte en ligne.
_CSP = (
    "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def create_app(corpus_dir: str | os.PathLike[str] | None = None) -> Flask:
    """Fabrique d'application. Aucun etat global, testable en isolation."""
    application = Flask(__name__)
    application.config["CORPUS_DIR"] = Path(corpus_dir or DEFAULT_CORPUS_DIR).resolve()
    application.config["JSON_SORT_KEYS"] = True
    # Un rapport est integralement recalcule a chaque requete : la mise en cache
    # est laissee a un reverse proxy, qui saura l'invalider sur l'empreinte du
    # corpus. Un cache applicatif servirait des chiffres dont on ne saurait plus
    # de quel corpus ils proviennent.
    application.config["ANALYSIS"] = AnalysisConfig(
        uncertainty=UncertaintyConfig(bootstrap=250, permutations=250)
    )

    @application.after_request
    def _harden(response: Response) -> Response:
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response

    def _available() -> list[dict[str, str]]:
        directory: Path = application.config["CORPUS_DIR"]
        if not directory.is_dir():
            return []
        entries = []
        for path in sorted(directory.glob("*.json")):
            try:
                dossier = load_dossier(path)
            except PrismeError:
                continue
            entries.append(
                {
                    "name": path.stem,
                    "label": dossier.label,
                    "qid": dossier.entity_qid,
                    "langs": ", ".join(dossier.langs),
                    "nature": dossier.snapshots[0].provenance.source_id,
                }
            )
        return entries

    def _report(name: str):
        path = resolve_corpus_path(name, application.config["CORPUS_DIR"])
        return analyse(load_dossier(path), application.config["ANALYSIS"])

    @application.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            corpora=_available(),
            version=__version__,
            method=METHOD_VERSION,
        )

    @application.get("/rapport/<name>")
    def report(name: str) -> str:
        try:
            return render_template("report.html", body=render_fragment(_report(name)))
        except PrismeError as exc:
            abort(404, description=str(exc))

    @application.get("/api/rapport/<name>")
    def report_json(name: str):
        try:
            return jsonify(to_payload(_report(name)))
        except PrismeError as exc:
            return jsonify({"error": str(exc)}), 404

    @application.get("/sante")
    def health():
        """Sonde de disponibilite. N'expose ni chemin, ni version d'interprete."""
        return jsonify({"status": "ok", "method_version": METHOD_VERSION})

    @application.errorhandler(404)
    def not_found(error):
        return (
            render_template("error.html", code=404, message=error.description),
            404,
        )

    return application


__all__ = ["create_app"]
