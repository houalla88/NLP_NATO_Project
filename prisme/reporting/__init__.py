"""Couche de restitution : export JSON auditable et rendu HTML."""

from .bundle import BUNDLE_SCHEMA, audit_manifest, to_payload, write_bundle
from .html import render_document, render_fragment

__all__ = [
    "BUNDLE_SCHEMA", "audit_manifest", "render_document", "render_fragment",
    "to_payload", "write_bundle",
]
