"""
Tests for fmdig.py pure functions.

Run: uv run --group dev pytest
"""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import fmdig without executing main() — works because of if __name__ guard
# ---------------------------------------------------------------------------
_path = Path(__file__).parent.parent / "fmdig.py"
_spec = importlib.util.spec_from_file_location("fmdig", _path)
assert _spec is not None and _spec.loader is not None, f"could not load {_path}"
fmdig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fmdig)


# ===========================================================================
# parse_since
# ===========================================================================


class TestParseSince:
    def _parse(self, s):
        result = fmdig.parse_since(s)
        return datetime.fromisoformat(result.replace("Z", "+00:00"))

    def test_hours(self):
        before = datetime.now(timezone.utc)
        dt = self._parse("24h")
        assert abs((before - timedelta(hours=24) - dt).total_seconds()) < 5

    def test_days(self):
        before = datetime.now(timezone.utc)
        dt = self._parse("7d")
        assert abs((before - timedelta(days=7) - dt).total_seconds()) < 5

    def test_weeks(self):
        before = datetime.now(timezone.utc)
        dt = self._parse("2w")
        assert abs((before - timedelta(weeks=2) - dt).total_seconds()) < 5

    def test_result_format_is_utc_z(self):
        result = fmdig.parse_since("1h")
        assert result.endswith("Z")
        assert "T" in result

    def test_invalid_unit_exits(self):
        with pytest.raises(SystemExit):
            fmdig.parse_since("3m")

    def test_no_unit_exits(self):
        with pytest.raises(SystemExit):
            fmdig.parse_since("24")

    def test_fractional_not_accepted(self):
        with pytest.raises(SystemExit):
            fmdig.parse_since("1.5h")


# ===========================================================================
# maybe_decode_qp
# ===========================================================================


class TestMaybeDecodeQP:
    def test_plain_passthrough(self):
        t = "Hello, world! No encoding here."
        assert fmdig.maybe_decode_qp(t) == t

    def test_hex_sequence_decoded(self):
        # "é" = U+00E9; in QP over latin-1: =C3=A9 (utf-8 bytes)
        result = fmdig.maybe_decode_qp("caf=C3=A9")
        assert "café" in result

    def test_soft_line_break_joined(self):
        # QP soft line break: "=" at end of line means "continue"
        result = fmdig.maybe_decode_qp("long lin=\ncontinued")
        assert "=" not in result
        assert "continued" in result

    def test_soft_line_break_crlf(self):
        result = fmdig.maybe_decode_qp("long lin=\r\ncontinued")
        assert "=" not in result
        assert "continued" in result

    def test_no_false_positive_on_equals(self):
        # plain "=" without hex suffix should not trigger QP decode
        t = "x = y + z"
        assert fmdig.maybe_decode_qp(t) == t


# ===========================================================================
# strip_html
# ===========================================================================


class TestStripHtml:
    def s(self, html):
        return fmdig.strip_html(html)

    # --- basic tag removal --------------------------------------------------

    def test_p_tag_content_kept(self):
        assert self.s("<p>Hello</p>") == "Hello"

    def test_nested_span_removed(self):
        assert self.s("<p><span>text</span></p>") == "text"

    # --- block elements → newlines -----------------------------------------

    def test_div_elements_separated(self):
        result = self.s("<div>A</div><div>B</div>")
        assert "A" in result and "B" in result
        assert result.index("A") < result.index("B")

    def test_br_becomes_newline(self):
        result = self.s("line1<br>line2")
        assert "\n" in result
        assert "line1" in result and "line2" in result

    def test_br_self_closing(self):
        result = self.s("line1<br/>line2")
        assert "\n" in result

    def test_td_cells_separated(self):
        result = self.s("<tr><td>Col1</td><td>Col2</td></tr>")
        assert "Col1" in result and "Col2" in result
        assert result.index("Col1") < result.index("Col2")

    def test_heading_becomes_newline(self):
        result = self.s("<h2>Title</h2><p>Body</p>")
        assert "Title" in result and "Body" in result

    # --- style / script / head removal ------------------------------------

    def test_style_block_removed(self):
        html = "<style>.nav { display: none; } .header { color: red; }</style><p>Content</p>"
        result = self.s(html)
        assert ".nav" not in result
        assert "Content" in result

    def test_script_block_removed(self):
        html = "<script>document.write('xss');</script><p>Safe</p>"
        result = self.s(html)
        assert "document.write" not in result
        assert "Safe" in result

    def test_head_block_removed(self):
        html = "<head><title>Page</title></head><body><p>Body</p></body>"
        result = self.s(html)
        assert "Page" not in result
        assert "Body" in result

    # --- HTML entities -------------------------------------------------------

    def test_lt_gt_unescaped(self):
        assert self.s("&lt;tag&gt;") == "<tag>"

    def test_nbsp_handled(self):
        result = self.s("word1&nbsp;word2")
        assert "word1" in result and "word2" in result

    def test_amp_unescaped(self):
        assert self.s("cats &amp; dogs") == "cats & dogs"

    # --- zero-width Unicode spacers -----------------------------------------

    def test_zero_width_space_removed(self):
        assert "\u200b" not in self.s("<p>He\u200bllo</p>")

    def test_soft_hyphen_removed(self):
        assert "\u00ad" not in self.s("<p>com\u00adplex</p>")

    def test_bom_removed(self):
        assert "\ufeff" not in self.s("\ufeff<p>text</p>")

    # --- tracking URL stripping ---------------------------------------------

    def test_long_url_stripped(self):
        long_url = "https://track.example.com/open/" + "a" * 50
        html = f"<p>Click <a href='{long_url}'>{long_url}</a> to unsubscribe</p>"
        result = self.s(html)
        assert long_url not in result
        assert "unsubscribe" in result

    def test_short_url_kept_in_text(self):
        # URL text under 60 chars stays; href is inside tag so gone either way
        html = "<a href='https://x.co'>https://x.co</a>"
        result = self.s(html)
        assert "https://x.co" in result

    def test_tracking_url_boundary_not_stripped(self):
        # regex is https?://\S{60,}: 59 chars AFTER "https://" → not stripped
        url = "https://" + "x" * 59  # 67 chars total
        result = self.s(f"<p>{url}</p>")
        assert url in result

    def test_tracking_url_boundary_stripped(self):
        # 60 chars AFTER "https://" → stripped (68 chars total)
        url = "https://" + "x" * 60  # 68 chars total
        result = self.s(f"<p>{url}</p>")
        assert url not in result

    # --- whitespace normalization -------------------------------------------

    def test_excess_blank_lines_collapsed(self):
        html = "<p>A</p>\n\n\n\n\n<p>B</p>"
        result = self.s(html)
        assert "\n\n\n" not in result

    def test_inline_whitespace_collapsed(self):
        result = self.s("<p>word1    word2\t\tword3</p>")
        assert "word1 word2 word3" in result

    def test_empty_html_returns_empty(self):
        assert self.s("") == ""

    def test_whitespace_only_lines_dropped(self):
        result = self.s("<p>   </p><p>text</p>")
        assert result == "text"

    # --- realistic email patterns -------------------------------------------

    def test_cisco_security_advisory(self):
        # Cisco-style: HTML table with actual content, tiny plain-text stub
        html = """
        <html><body>
        <table><tr><td>
          <h2>Security Advisory</h2>
          <p>Cisco has released advisories for IOS XE.</p>
          <p>CVE-2025-99999 affects release 17.x and earlier.</p>
          <p>Workaround: disable HTTP server with <code>no ip http server</code>.</p>
        </td></tr></table>
        </body></html>
        """
        result = self.s(html)
        assert "Security Advisory" in result
        assert "CVE-2025-99999" in result
        assert "no ip http server" in result

    def test_marketing_email_with_tracking_urls(self):
        # Marketing template with multiple tracking links and navigation noise
        html = """
        <html><body>
        <style>.btn { padding: 10px; }</style>
        <div class="header">Company Newsletter</div>
        <div class="body">
          <p>Here is your monthly update.</p>
          <p>Read more at https://click.mailchimp.com/track/click/12345/longtoken_abc_XYZ_tracking_deadbeef_cafebabe_final/here</p>
        </div>
        <div class="footer">
          Unsubscribe: https://track.example.com/unsub/user_abc123_token_xxxxxxxxxxxxxxxxxxxxxxxx_end
        </div>
        </body></html>
        """
        result = self.s(html)
        assert "monthly update" in result
        assert ".btn" not in result
        # long tracking URLs should be gone
        assert "click.mailchimp.com" not in result
        assert "track.example.com" not in result

    def test_multipart_table_layout(self):
        # Table-based two-column layout common in corporate emails
        html = """
        <table>
          <tr>
            <th>Product</th><th>Price</th><th>Qty</th>
          </tr>
          <tr>
            <td>Widget A</td><td>$10.00</td><td>3</td>
          </tr>
          <tr>
            <td>Widget B</td><td>$25.00</td><td>1</td>
          </tr>
        </table>
        """
        result = self.s(html)
        assert "Product" in result
        assert "Widget A" in result
        assert "$10.00" in result
        assert "Widget B" in result
        # columns should appear in order
        assert result.index("Product") < result.index("Widget A")
        assert result.index("Widget A") < result.index("Widget B")


# ===========================================================================
# JMAP.search — filter construction
# ===========================================================================


def _make_jmap_client():
    """Return a JMAP instance with httpx mocked out."""
    session_data = {
        "primaryAccounts": {"urn:ietf:params:jmap:mail": "account1"},
        "apiUrl": "https://api.fastmail.com/jmap/api",
        "downloadUrl": "https://dl.fastmail.com/{accountId}/{blobId}/{type}/{name}",
    }
    session_resp = MagicMock()
    session_resp.json.return_value = session_data
    session_resp.raise_for_status = MagicMock()

    mock_http = MagicMock()
    mock_http.get.return_value = session_resp

    with (
        patch("fmdig.resolve_token", return_value="fake-token"),
        patch("httpx.Client", return_value=mock_http),
    ):
        client = fmdig.JMAP()

    client.http = mock_http
    return client, mock_http


def _stub_search_response(mock_http, mailboxes=None, email_ids=None):
    """Set up mock_http.post to return a minimal valid search response."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "methodResponses": [
            ["Mailbox/get", {"list": mailboxes or []}, "mb"],
            ["Email/query", {"ids": email_ids or []}, "q"],
            ["Email/get", {"list": []}, "e"],
        ]
    }
    mock_http.post.return_value = resp
    return resp


def _posted_filter(mock_http):
    """Extract the Email/query filter from the last POST call."""
    call_kwargs = mock_http.post.call_args
    body = call_kwargs[1].get("json") or call_kwargs[0][1]
    calls = body["methodCalls"]
    eq = next(c for c in calls if c[0] == "Email/query")
    return eq[1]["filter"]


class TestSearchFilterConstruction:
    def test_plain_query_passthrough(self):
        client, mock_http = _make_jmap_client()
        _stub_search_response(mock_http)

        client.search('{"text": "invoice"}', limit=10)

        filt = _posted_filter(mock_http)
        assert filt == {"text": "invoice"}

    def test_since_injects_after(self):
        client, mock_http = _make_jmap_client()
        _stub_search_response(mock_http)

        before = datetime.now(timezone.utc)
        client.search('{"text": "invoice"}', limit=10, since="7d")

        filt = _posted_filter(mock_http)
        assert filt["text"] == "invoice"
        assert "after" in filt
        after_dt = datetime.fromisoformat(filt["after"].replace("Z", "+00:00"))
        expected = before - timedelta(days=7)
        assert abs((after_dt - expected).total_seconds()) < 5

    def test_since_with_operator_filter_wraps_in_and(self):
        client, mock_http = _make_jmap_client()
        _stub_search_response(mock_http)

        client.search(
            '{"operator":"OR","conditions":[{"from":"a@x.com"},{"from":"b@x.com"}]}',
            limit=10,
            since="24h",
        )

        filt = _posted_filter(mock_http)
        assert filt["operator"] == "AND"
        conditions = filt["conditions"]
        assert any(c.get("operator") == "OR" for c in conditions)
        assert any("after" in c for c in conditions)

    def test_since_with_existing_after_wraps_in_and(self):
        client, mock_http = _make_jmap_client()
        _stub_search_response(mock_http)

        client.search(
            '{"from":"a@x.com","after":"2026-01-01T00:00:00Z"}', limit=10, since="7d"
        )

        filt = _posted_filter(mock_http)
        assert filt["operator"] == "AND"

    def test_inmailbox_other_than_passthrough(self):
        # Spam exclusion pattern: inMailboxOtherThan in query JSON
        client, mock_http = _make_jmap_client()
        _stub_search_response(mock_http)

        client.search(
            '{"text":"meeting","inMailboxOtherThan":["spam_id","trash_id"]}',
            limit=10,
        )

        filt = _posted_filter(mock_http)
        assert filt["inMailboxOtherThan"] == ["spam_id", "trash_id"]
        assert filt["text"] == "meeting"

    def test_invalid_json_exits(self):
        client, mock_http = _make_jmap_client()

        with pytest.raises(SystemExit):
            client.search("{not valid json}", limit=10)
