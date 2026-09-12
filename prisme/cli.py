"""Interface en ligne de commande.

Cinq verbes couvrent le cycle complet : etalonner l'instrument, collecter,
analyser, restituer, servir. Chaque commande qui produit un resultat ecrit
systematiquement le triptyque JSON + HTML + manifeste d'audit : un rapport
sans son manifeste n'est pas opposable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import METHOD_VERSION, __version__
from .config import Settings
from .domain.errors import PrismeError
from .metrics.distributions import SmoothingPolicy
from .metrics.divergence import UncertaintyConfig
from .pipeline import AnalysisConfig, analyse
from .reporting import audit_manifest, render_document, write_bundle


def _emit(report, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = write_bundle(report, out_dir / f"{stem}.json")
    page = out_dir / f"{stem}.html"
    page.write_text(render_document(report), encoding="utf-8")
    manifest = out_dir / f"{stem}.audit.txt"
    manifest.write_text(audit_manifest(report), encoding="utf-8")

    print(f"  rapport JSON : {bundle}")
    print(f"  rapport HTML : {page}")
    print(f"  manifeste    : {manifest}")
    print()
    print(f"  nature des donnees : {report.data_nature}")
    print(f"  editions           : {', '.join(report.langs)}")
    print(f"  cadrage singulier  : {report.most_isolated_lang()}")
    for warning in report.warnings:
        print(f"  ! {warning}")


def _analysis_config(args: argparse.Namespace) -> AnalysisConfig:
    return AnalysisConfig(
        smoothing=SmoothingPolicy(kind=getattr(args, "smoothing", "none")),
        uncertainty=UncertaintyConfig(
            bootstrap=getattr(args, "bootstrap", 400),
            permutations=getattr(args, "permutations", 400),
            seed=getattr(args, "seed", 20260912),
        ),
    )


def cmd_calibrate(args: argparse.Namespace) -> int:
    from .calibration import run_calibration

    print(f"Banc d'etalonnage PRISME - methode {METHOD_VERSION}\n")
    result = run_calibration(seed=args.seed, fast=args.fast)
    print(result.report())
    if not result.passed:
        print("\nDetail des controles en echec :")
        for check in result.checks:
            if not check.passed:
                print(f"  - {check.name}: {check.detail}")
    return 0 if result.passed else 1


def cmd_demo(args: argparse.Namespace) -> int:
    from .scenarios import build_demo_dossier

    print("Scenario de DEMONSTRATION - corpus genere, aucune valeur empirique.\n")
    dossier = build_demo_dossier(seed=args.seed)
    report = analyse(dossier, _analysis_config(args))
    _emit(report, Path(args.out), "demo")
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    from .sources.local import LocalCorpusSource, load_dossier

    path = Path(args.corpus)
    dossier = (
        LocalCorpusSource(path).fetch("", args.langs.split(",") if args.langs else [])
        if args.langs
        else load_dossier(path)
    )
    report = analyse(
        dossier,
        _analysis_config(args),
        requested_langs=args.langs.split(",") if args.langs else None,
    )
    _emit(report, Path(args.out), path.stem)
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    from .sources.local import dump_dossier
    from .sources.mediawiki import MediaWikiSource

    langs = [code.strip() for code in args.langs.split(",") if code.strip()]
    print(f"Collecte de {args.qid} sur {len(langs)} editions : {', '.join(langs)}")
    print("Source : API MediaWiki / Wikidata (publique, anonyme).\n")

    source = MediaWikiSource(Settings.from_env())
    dossier = source.fetch(args.qid, langs, revision_limit=args.revisions)
    target = dump_dossier(dossier, "recorded-live", Path(args.out))

    print(f"  corpus fige : {target}")
    print(f"  editions obtenues : {', '.join(dossier.langs)}")
    missing = sorted(set(langs) - set(dossier.langs))
    if missing:
        print(f"  ! editions sans article ou inaccessibles : {', '.join(missing)}")
    print("\nAnalyser ensuite :")
    print(f"  prisme analyse --corpus {target}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        from app import create_app
    except ImportError:
        print(
            "L'interface web requiert Flask, qui n'est pas une dependance du moteur.\n"
            "  pip install 'prisme[app]'",
            file=sys.stderr,
        )
        return 2

    application = create_app()
    print(f"PRISME sur http://{args.host}:{args.port}  (Ctrl+C pour arreter)")
    application.run(host=args.host, port=args.port, debug=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prisme",
        description=(
            "Mesure auditable de la divergence narrative entre editions "
            "linguistiques de Wikipedia."
        ),
    )
    parser.add_argument("--version", action="version", version=f"prisme {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--out", default="out", help="repertoire de sortie")
        target.add_argument("--seed", type=int, default=20260912)
        target.add_argument("--bootstrap", type=int, default=400)
        target.add_argument("--permutations", type=int, default=400)
        target.add_argument(
            "--smoothing", choices=("none", "laplace", "dirichlet"), default="none"
        )

    calibrate = sub.add_parser(
        "calibrate", help="verifier l'instrument sur corpus a divergence connue"
    )
    calibrate.add_argument("--fast", action="store_true")
    calibrate.add_argument("--seed", type=int, default=4242)
    calibrate.set_defaults(func=cmd_calibrate)

    demo = sub.add_parser("demo", help="produire un rapport de demonstration (synthetique)")
    add_common(demo)
    demo.set_defaults(func=cmd_demo)

    analyse_cmd = sub.add_parser("analyse", help="analyser un corpus local")
    analyse_cmd.add_argument("--corpus", required=True)
    analyse_cmd.add_argument("--langs", default="", help="sous-ensemble, ex. ru,en,fr")
    add_common(analyse_cmd)
    analyse_cmd.set_defaults(func=cmd_analyse)

    collect = sub.add_parser("collect", help="collecter et figer un corpus depuis Wikimedia")
    collect.add_argument("--qid", required=True, help="identifiant Wikidata, ex. Q7184")
    collect.add_argument("--langs", required=True, help="ex. ru,en,fr,de,pl,uk")
    collect.add_argument("--out", required=True, help="fichier corpus JSON a ecrire")
    collect.add_argument("--revisions", type=int, default=500)
    collect.set_defaults(func=cmd_collect)

    serve = sub.add_parser("serve", help="lancer l'interface web (Flask)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5000)
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PrismeError as exc:
        # Les erreurs du domaine sont attendues : message lisible, pas de trace.
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
