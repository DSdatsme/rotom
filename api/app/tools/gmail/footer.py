"""Pure builders for the subtle "Sent with rotom" attribution footer.

No I/O, no settings, no MIME — just strings, so it's trivially unit-tested.
The footer is appended below the email body (which already carries the user's
personal sign-off) at send/save time; it is never stored in the draft.
"""

import html

_PHRASE = "Sent with rotom"


def plain_footer(url: str) -> str:
    """Plain-text footer line for the text/plain alternative."""
    return f"\n\n{_PHRASE} · {url}"


def html_body(body: str, url: str) -> str:
    """Render the plain-text body as a minimal HTML document with the anchor footer.

    Body is HTML-escaped and newlines become <br>. All styling is inline because
    email clients strip <style>/<head>. The footer is muted and small.
    """
    safe_body = html.escape(body).replace("\n", "<br>")
    safe_url = html.escape(url, quote=True)
    footer = (
        '<div style="margin-top:24px;color:#9ca3af;font-size:12px;">'
        f'Sent with <a href="{safe_url}" '
        'style="color:#9ca3af;text-decoration:underline;">rotom</a></div>'
    )
    return (
        '<div style="font-family:sans-serif;font-size:14px;color:#111;">'
        f"{safe_body}{footer}</div>"
    )
