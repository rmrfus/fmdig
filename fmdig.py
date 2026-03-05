#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "keyring"]
# ///

import os
import re
import sys
import json
import html
import quopri
import getpass
import argparse
from datetime import datetime, timezone, timedelta

import keyring
import httpx
from typing import NoReturn

DEFAULT_SESSION_URL = "https://api.fastmail.com/jmap/session"
KEYRING_SERVICE = "fmdig"
KEYRING_ACCOUNT = "fmdig"


def die(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def keyring_get() -> str | None:
    return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)


def keyring_set(token: str) -> None:
    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, token)


def resolve_token() -> str:
    token = os.environ.get("JMAP_TOKEN") or keyring_get()
    if not token:
        die("no token found: set JMAP_TOKEN or run `fmdig login`")
    return token


def parse_since(value: str) -> str:
    """Parse a relative time like '24h', '7d', '2w' into an ISO 8601 UTC string."""
    units = {"h": 3600, "d": 86400, "w": 604800}
    m = re.fullmatch(r"(\d+)([hdw])", value.strip())
    if not m:
        die(f"invalid --since value {value!r}: use e.g. 24h, 7d, 2w")
    seconds = int(m.group(1)) * units[m.group(2)]
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def maybe_decode_qp(text: str) -> str:
    if re.search(r"=[0-9A-Fa-f]{2}|=\r?\n", text):
        try:
            return quopri.decodestring(text.encode("latin-1")).decode("utf-8", errors="replace")
        except Exception:
            pass
    return text


def strip_html(raw: str) -> str:
    text = re.sub(r"<(style|script|head)[^>]*>.*?</\1>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(?:p|div|tr|td|th|li|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # collapse whitespace within lines, then drop blank/whitespace-only lines
    # strip tracking URLs (long URLs that add noise without readable context)
    text = re.sub(r"https?://\S{60,}", "", text)
    # strip zero-width and other invisible Unicode spacers used in email templates
    text = re.sub(r"[\u200b-\u200f\u00ad\ufeff]", "", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class JMAP:
    def __init__(self):
        session_url = os.environ.get("JMAP_SESSION_URL", DEFAULT_SESSION_URL)
        token = resolve_token()

        self.http = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r = self.http.get(session_url)
        r.raise_for_status()
        s = r.json()
        self.account_id = s["primaryAccounts"]["urn:ietf:params:jmap:mail"]
        self.api_url = s["apiUrl"]
        self.download_url = s["downloadUrl"]
        self._mailbox_cache: dict | None = None

    def _call(self, method_calls: list) -> list:
        r = self.http.post(self.api_url, json={
            "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
            "methodCalls": method_calls,
        })
        r.raise_for_status()
        responses = r.json()["methodResponses"]
        for name, data, _ in responses:
            if name == "error":
                die(f"JMAP error: {data.get('type')}: {data.get('description', '')}")
        return responses

    def _all_mailboxes(self) -> list:
        resp = self._call([
            ["Mailbox/get", {"accountId": self.account_id, "ids": None}, "0"]
        ])
        return resp[0][1]["list"]

    def _mailbox_map(self) -> dict:
        if self._mailbox_cache is None:
            self._mailbox_cache = {m["id"]: m["name"] for m in self._all_mailboxes()}
        return self._mailbox_cache

    def _resolve_mailbox(self, name: str) -> str:
        for mid, mname in self._mailbox_map().items():
            if mname.lower() == name.lower():
                return mid
        die(f"mailbox not found: {name!r}")

    def folders(self):
        mailboxes = self._all_mailboxes()
        mailboxes.sort(key=lambda m: (m.get("sortOrder", 999), m.get("name", "")))
        print(f"{'NAME':<30} {'UNREAD':>6} {'TOTAL':>7}  ID")
        print("-" * 72)
        for m in mailboxes:
            name = m.get("name", "")
            unread = m.get("unreadEmails", 0)
            total = m.get("totalEmails", 0)
            print(f"{name:<30} {unread:>6} {total:>7}  {m['id']}")

    def list_emails(self, mailbox_name: str, limit: int, since: str | None = None, preview: bool = False):
        mailbox_id = self._resolve_mailbox(mailbox_name)
        filt: dict = {"inMailbox": mailbox_id}
        if since:
            filt["after"] = parse_since(since)
        props = ["id", "from", "subject", "receivedAt"]
        if preview:
            props.append("preview")
        resp = self._call([
            ["Email/query", {
                "accountId": self.account_id,
                "filter": filt,
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": limit,
            }, "0"],
            ["Email/get", {
                "accountId": self.account_id,
                "#ids": {"resultOf": "0", "name": "Email/query", "path": "/ids"},
                "properties": props,
            }, "1"],
        ])
        self._print_list(resp[1][1]["list"], preview=preview)

    def search(self, query_json: str, limit: int, since: str | None = None, preview: bool = False):
        try:
            filt = json.loads(query_json)
        except json.JSONDecodeError as e:
            die(f"invalid JSON query: {e}")

        if since:
            after_iso = parse_since(since)
            # wrap in AND if filter already has an "after" key or is an operator filter
            if "operator" in filt or "after" in filt:
                filt = {"operator": "AND", "conditions": [filt, {"after": after_iso}]}
            else:
                filt["after"] = after_iso

        props = ["id", "from", "subject", "receivedAt", "mailboxIds"]
        if preview:
            props.append("preview")

        # fetch mailbox map in the same batch
        resp = self._call([
            ["Mailbox/get", {"accountId": self.account_id, "ids": None}, "mb"],
            ["Email/query", {
                "accountId": self.account_id,
                "filter": filt,
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": limit,
            }, "q"],
            ["Email/get", {
                "accountId": self.account_id,
                "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
                "properties": props,
            }, "e"],
        ])
        mb_map = {m["id"]: m["name"] for m in resp[0][1]["list"]}
        self._mailbox_cache = mb_map
        self._print_list(resp[2][1]["list"], show_mailbox=True, preview=preview)

    def _print_list(self, emails: list, show_mailbox: bool = False, preview: bool = False):
        if not emails:
            print("(no messages)")
            return

        # column widths
        w_date, w_from, w_subj = 14, 28, 60
        header = f"{'DATE':<{w_date}} {'FROM':<{w_from}} {'SUBJECT':<{w_subj}}"
        if show_mailbox:
            header += f"  {'MAILBOX':<14}"
        header += "  ID"
        print(header)
        print("-" * len(header))

        for e in emails:
            date_str = ""
            if e.get("receivedAt"):
                dt = datetime.fromisoformat(e["receivedAt"]).astimezone()
                date_str = dt.strftime("%b %d %H:%M")

            from_list = e.get("from") or []
            addr = from_list[0] if from_list else {}
            from_str = addr.get("name") or addr.get("email", "")
            subject = e.get("subject") or "(no subject)"

            line = (f"{date_str:<{w_date}} {from_str[:w_from-1]:<{w_from}}"
                    f" {subject[:w_subj-1]:<{w_subj}}")

            if show_mailbox:
                mb_ids = list((e.get("mailboxIds") or {}).keys())
                mb_name = self._mailbox_cache.get(mb_ids[0], "?") if mb_ids and self._mailbox_cache else "?"
                line += f"  {mb_name[:13]:<14}"

            line += f"  {e['id']}"
            print(line)

            if preview and e.get("preview"):
                snippet = e["preview"].replace("\n", " ").strip()[:120]
                print(f"  > {snippet}")

    def cat(self, email_ids: list[str], raw: bool = False, max_body_kb: int = 100):
        if raw and len(email_ids) > 1:
            die("--raw does not support multiple IDs (binary output cannot be safely concatenated)")
        for email_id in email_ids:
            if raw:
                self._cat_raw(email_id)
            else:
                if len(email_ids) > 1:
                    print(f"\n{'=' * 72}")
                    print(f"ID: {email_id}")
                    print('=' * 72)
                self._cat_parsed(email_id, max_body_bytes=max_body_kb * 1024)

    def _cat_raw(self, email_id: str):
        resp = self._call([
            ["Email/get", {
                "accountId": self.account_id,
                "ids": [email_id],
                "properties": ["blobId"],
            }, "0"]
        ])
        emails = resp[0][1]["list"]
        if not emails:
            die(f"email not found: {email_id!r}")
        blob_id = emails[0]["blobId"]
        url = (self.download_url
               .replace("{accountId}", self.account_id)
               .replace("{blobId}", blob_id)
               .replace("{type}", "message%2Frfc822")
               .replace("{name}", "email.eml"))
        r = self.http.get(url)
        r.raise_for_status()
        sys.stdout.buffer.write(r.content)

    def _cat_parsed(self, email_id: str, max_body_bytes: int = 102400):
        resp = self._call([
            ["Email/get", {
                "accountId": self.account_id,
                "ids": [email_id],
                "properties": [
                    "from", "to", "cc",
                    "subject", "receivedAt",
                    "textBody", "htmlBody", "bodyValues", "attachments",
                ],
                "fetchTextBodyValues": True,
                "fetchHTMLBodyValues": True,
                "maxBodyValueBytes": max_body_bytes,
            }, "0"]
        ])
        emails = resp[0][1]["list"]
        if not emails:
            die(f"email not found: {email_id!r}")
        e = emails[0]

        def fmt_addrs(field: str) -> str:
            addrs = e.get(field) or []
            parts = []
            for a in addrs:
                if a.get("name"):
                    parts.append(f"{a['name']} <{a.get('email', '')}>")
                else:
                    parts.append(a.get("email", ""))
            return ", ".join(parts)

        date_str = ""
        if e.get("receivedAt"):
            dt = datetime.fromisoformat(e["receivedAt"]).astimezone()
            date_str = dt.strftime("%a, %d %b %Y %H:%M %z")

        print(f"From:    {fmt_addrs('from')}")
        print(f"To:      {fmt_addrs('to')}")
        if e.get("cc"):
            print(f"Cc:      {fmt_addrs('cc')}")
        print(f"Subject: {e.get('subject', '')}")
        print(f"Date:    {date_str}")
        print()

        body_values = e.get("bodyValues") or {}
        truncated = any(v.get("isTruncated") for v in body_values.values())

        # look for an explicit text/plain part
        body_text = None
        for part in (e.get("textBody") or []):
            if part.get("type", "") != "text/plain":
                continue
            part_id = part.get("partId")
            if part_id and part_id in body_values:
                body_text = maybe_decode_qp(body_values[part_id].get("value", ""))
                break

        # fall back to html if plain text is absent or a stub (< 200 chars after stripping)
        if not body_text or len(body_text.strip()) < 200:
            for part in (e.get("htmlBody") or []):
                part_id = part.get("partId")
                if part_id and part_id in body_values:
                    raw_html = maybe_decode_qp(body_values[part_id].get("value", ""))
                    html_text = strip_html(raw_html)
                    if html_text and len(html_text) > len(body_text or ""):
                        body_text = html_text
                    break

        print(body_text or "(no body)")

        attachments = e.get("attachments") or []
        if attachments:
            print()
            print("--- attachments ---")
            for a in attachments:
                name = a.get("name") or "(unnamed)"
                size = a.get("size") or 0
                ctype = a.get("type") or "?"
                print(f"  {name}  ({size // 1024} KB, {ctype})")

        if truncated:
            print("\n[body truncated — rerun with --max-body N to fetch more (default 100 KB)]")


def main():
    parser = argparse.ArgumentParser(prog="fmdig", description="Fastmail JMAP CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="store Fastmail API token in system keyring")

    sub.add_parser("folders", help="list mailboxes")

    p_list = sub.add_parser("list", help="list emails in a mailbox")
    p_list.add_argument("mailbox", help="mailbox name, e.g. Inbox")
    p_list.add_argument("--limit", type=int, default=50, metavar="N")
    p_list.add_argument("--since", metavar="AGO", help="only emails newer than this: 24h, 7d, 2w")
    p_list.add_argument("--preview", action="store_true", help="show body snippet under each email")

    p_search = sub.add_parser("search", help="search emails with JMAP filter")
    p_search.add_argument("--query", required=True,
                          help='JMAP FilterCondition JSON, e.g. \'{"text": "invoice"}\'')
    p_search.add_argument("--limit", type=int, default=50, metavar="N")
    p_search.add_argument("--since", metavar="AGO",
                          help="only emails newer than this: 24h, 7d, 2w")
    p_search.add_argument("--preview", action="store_true",
                          help="show server-generated 256-char snippet (unreliable for HTML-only mail)")

    p_cat = sub.add_parser("cat", help="show parsed email (default) or raw RFC 2822 (--raw)")
    p_cat.add_argument("ids", nargs="+", metavar="id", help="one or more email IDs from list/search")
    p_cat.add_argument("--raw", action="store_true", help="dump raw RFC 2822 instead of parsed text")
    p_cat.add_argument("--max-body", type=int, default=100, metavar="KB",
                       help="max body size to fetch in KB (default 100)")

    args = parser.parse_args()

    if args.cmd == "login":
        token = getpass.getpass("Fastmail API token: ")
        if not token:
            die("empty token")
        keyring_set(token)
        print("token saved to keyring")
        return

    client = JMAP()

    if args.cmd == "folders":
        client.folders()
    elif args.cmd == "list":
        client.list_emails(args.mailbox, args.limit, since=args.since, preview=args.preview)
    elif args.cmd == "search":
        client.search(args.query, args.limit, since=args.since, preview=args.preview)
    elif args.cmd == "cat":
        client.cat(args.ids, raw=args.raw, max_body_kb=args.max_body)


if __name__ == "__main__":
    main()
