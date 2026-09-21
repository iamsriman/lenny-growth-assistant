"""Artifact sanitisation — layer 1 of 3.

Model output is untrusted input. The layers are:

  1. This module: strip dangerous markup server-side and record *what* was
     removed, so the viewer can show the user a report instead of failing
     silently.
  2. A CSP `<meta>` injected into the document we hand back, blocking network
     egress and inline event handlers at the browser level.
  3. The frontend renders into a cross-origin `<iframe srcdoc>` with a
     `sandbox` attribute that never includes `allow-same-origin`, so even if
     layers 1 and 2 were bypassed the script has no access to our origin,
     cookies, or localStorage.

Layer 3 is the one that actually contains an attacker. Layers 1 and 2 exist so
that an accident (a model pasting a tracking pixel) is caught early and
visibly.
"""

from __future__ import annotations

import logging
import re

import bleach
from bleach.css_sanitizer import CSSSanitizer

log = logging.getLogger("app.artifact")

ALLOWED_TAGS = sorted({
    "a", "abbr", "article", "aside", "b", "blockquote", "br", "button", "canvas",
    "caption", "cite", "code", "col", "colgroup", "dd", "del", "details", "div",
    "dl", "dt", "em", "fieldset", "figcaption", "figure", "footer", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "i", "img", "input", "label", "legend",
    "li", "main", "mark", "nav", "ol", "optgroup", "option", "p", "pre", "progress",
    "q", "s", "section", "select", "small", "span", "strong", "style", "sub",
    "summary", "sup", "svg", "path", "circle", "rect", "line", "polyline",
    "polygon", "g", "text", "table", "tbody", "td", "tfoot", "th", "thead", "time",
    "tr", "u", "ul", "meta", "title", "head", "body", "html", "textarea",
})

_COMMON_ATTRS = ["class", "id", "style", "title", "role", "aria-label",
                 "aria-hidden", "aria-describedby", "data-label"]

ALLOWED_ATTRS: dict[str, list[str]] = {
    "*": _COMMON_ATTRS,
    "a": _COMMON_ATTRS + ["href", "target", "rel"],
    "img": _COMMON_ATTRS + ["src", "alt", "width", "height", "loading"],
    "input": _COMMON_ATTRS + ["type", "value", "placeholder", "name", "min", "max",
                              "step", "checked", "disabled", "readonly"],
    "textarea": _COMMON_ATTRS + ["rows", "cols", "placeholder", "name"],
    "select": _COMMON_ATTRS + ["name", "multiple"],
    "option": _COMMON_ATTRS + ["value", "selected"],
    "button": _COMMON_ATTRS + ["type", "disabled", "value"],
    "td": _COMMON_ATTRS + ["colspan", "rowspan"],
    "th": _COMMON_ATTRS + ["colspan", "rowspan", "scope"],
    "progress": _COMMON_ATTRS + ["value", "max"],
    "meta": ["charset", "name", "content", "http-equiv"],
    "svg": _COMMON_ATTRS + ["viewBox", "xmlns", "width", "height", "fill", "stroke",
                            "preserveAspectRatio"],
    "path": _COMMON_ATTRS + ["d", "fill", "stroke", "stroke-width", "stroke-linecap",
                             "fill-rule", "clip-rule"],
    "circle": _COMMON_ATTRS + ["cx", "cy", "r", "fill", "stroke", "stroke-width"],
    "rect": _COMMON_ATTRS + ["x", "y", "width", "height", "rx", "ry", "fill", "stroke"],
    "line": _COMMON_ATTRS + ["x1", "y1", "x2", "y2", "stroke", "stroke-width"],
    "polyline": _COMMON_ATTRS + ["points", "fill", "stroke", "stroke-width"],
    "polygon": _COMMON_ATTRS + ["points", "fill", "stroke", "stroke-width"],
    "g": _COMMON_ATTRS + ["fill", "stroke", "transform"],
    "text": _COMMON_ATTRS + ["x", "y", "fill", "font-size", "text-anchor",
                             "font-family", "font-weight"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]

_CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=None,  # allow the property set bleach ships with
    allowed_svg_properties=None,
)

_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_SCRIPT_OPEN = re.compile(r"<\s*/?\s*(script|iframe|object|embed|base|link|form|meta"
                          r"\s+http-equiv\s*=\s*[\"']?refresh)\b[^>]*>", re.IGNORECASE)
_EVENT_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_URL = re.compile(r"(href|src|action)\s*=\s*([\"']?)\s*(javascript|vbscript):",
                     re.IGNORECASE)
_DATA_HTML = re.compile(r"(href|src)\s*=\s*([\"']?)\s*data:text/html", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)

CSP = (
    "default-src 'none'; "
    "img-src data: https:; "
    "style-src 'unsafe-inline'; "
    "font-src data:; "
    "script-src 'unsafe-inline'; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "base-uri 'none'"
)


def strip_code_fence(text: str) -> str:
    match = _FENCE.match(text.strip())
    return match.group(1) if match else text.strip()


def sanitize_html(raw: str, *, allow_scripts: bool = False) -> tuple[str, dict]:
    """Return (safe_document, report).

    `allow_scripts=True` keeps `<script>` blocks. That is only safe because of
    layer 3: the iframe is cross-origin, so the script can animate its own
    document and nothing else. The report tells the user scripts are present.
    """
    source = strip_code_fence(raw)
    report: dict = {"removed": [], "scripts_kept": 0, "original_bytes": len(source)}

    scripts: list[str] = []
    if allow_scripts:
        def _stash(match: re.Match) -> str:
            body = re.sub(r"^<script\b[^>]*>|</script\s*>$", "", match.group(0),
                          flags=re.IGNORECASE)
            if _JS_URL.search(body) or "document.cookie" in body or "localStorage" in body:
                report["removed"].append("script accessing storage/cookies")
                return ""
            scripts.append(body)
            return f"<!--LGA_SCRIPT_{len(scripts) - 1}-->"
        source = _SCRIPT_BLOCK.sub(_stash, source)
    elif _SCRIPT_BLOCK.search(source):
        source = _SCRIPT_BLOCK.sub("", source)
        report["removed"].append("script")

    if _SCRIPT_OPEN.search(source):
        source = _SCRIPT_OPEN.sub("", source)
        report["removed"].append("iframe/object/embed/base/link/form/meta-refresh")
    if _EVENT_ATTR.search(source):
        source = _EVENT_ATTR.sub("", source)
        report["removed"].append("inline event handler")
    if _JS_URL.search(source):
        source = _JS_URL.sub(r"\1=\2#blocked:", source)
        report["removed"].append("javascript: url")
    if _DATA_HTML.search(source):
        source = _DATA_HTML.sub(r"\1=\2#blocked:", source)
        report["removed"].append("data:text/html url")

    cleaned = bleach.clean(
        source,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
        strip_comments=False,
    )

    for i, body in enumerate(scripts):
        cleaned = cleaned.replace(f"<!--LGA_SCRIPT_{i}-->", f"<script>{body}</script>")
    report["scripts_kept"] = len(scripts)

    document = _wrap_document(cleaned)
    report["clean_bytes"] = len(document)
    report["removed"] = sorted(set(report["removed"]))
    if report["removed"]:
        log.info("artifact sanitised", extra={"component": "artifact",
                                              "removed": report["removed"]})
    return document, report


def _wrap_document(body_html: str) -> str:
    """Guarantee a full document with our CSP, whatever shape the model emitted."""
    has_html = re.search(r"<html\b", body_html, re.IGNORECASE)
    csp_tag = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    base_css = (
        "<style>:root{color-scheme:light dark}"
        "body{margin:0;padding:24px;font-family:ui-sans-serif,system-ui,"
        "-apple-system,'Segoe UI',Roboto,sans-serif;line-height:1.6;"
        "background:#fff;color:#16181c}"
        "img,svg,table{max-width:100%}</style>"
    )
    if has_html:
        if re.search(r"<head\b", body_html, re.IGNORECASE):
            return re.sub(r"(<head\b[^>]*>)", r"\1" + csp_tag + base_css,
                          body_html, count=1, flags=re.IGNORECASE)
        return re.sub(r"(<html\b[^>]*>)", r"\1<head>" + csp_tag + base_css + "</head>",
                      body_html, count=1, flags=re.IGNORECASE)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"{csp_tag}{base_css}</head><body>{body_html}</body></html>"
    )


def sanitize_markdown(raw: str) -> tuple[str, dict]:
    """Markdown is rendered by the frontend, not by a browser parser.

    We still strip raw HTML blocks so a Markdown artifact cannot smuggle a
    script through a renderer configured with `rehype-raw`.
    """
    source = strip_code_fence(raw)
    report: dict = {"removed": [], "original_bytes": len(source)}
    if _SCRIPT_BLOCK.search(source) or _SCRIPT_OPEN.search(source):
        source = _SCRIPT_OPEN.sub("", _SCRIPT_BLOCK.sub("", source))
        report["removed"].append("embedded html/script")
    if _JS_URL.search(source) or "](javascript:" in source.lower():
        source = _JS_URL.sub(r"\1=\2#blocked:", source)
        source = re.sub(r"\]\(\s*javascript:[^)]*\)", "](#blocked)", source,
                        flags=re.IGNORECASE)
        report["removed"].append("javascript: link")
    report["clean_bytes"] = len(source)
    return source, report
