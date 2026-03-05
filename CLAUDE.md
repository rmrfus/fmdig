# fmdig

Read-only Fastmail CLI via JMAP API.

## Structure

Single file: `fmdig.py`. Runs via uv shebang with inline dependencies.

## Dependencies

- `httpx` — HTTP client
- `keyring` — token storage (macOS Keychain, GNOME Keyring, KWallet)

## Configuration

| Variable | Default | Description |
|---|---|---|
| `JMAP_TOKEN` | — | Fastmail API token (takes priority over keyring) |
| `JMAP_SESSION_URL` | `https://api.fastmail.com/jmap/session` | JMAP session endpoint |

Token can be stored in system keyring: `./fmdig.py login`

## Commands

```
login                              save token to keyring (interactive, no echo)
folders                            list mailboxes with unread/total counts
list <mailbox> [--limit N]         list emails in a mailbox (default 50)
  [--since AGO]                    only emails newer than this: 24h, 7d, 2w
  [--preview]                      show server-generated snippet per row
search --query '<json>'            search with JMAP FilterCondition JSON
  [--limit N] [--since AGO]        AGO: 24h, 7d, 2w — injects "after" into filter
  [--preview]                      also shows MAILBOX column
cat <id> [<id2> ...]               parsed email(s); separator printed between multiple
  [--raw]                          raw RFC 2822 blob (single ID only)
  [--max-body KB]                  max body fetch size in KB (default 100)
```

## Architecture notes

- `_call()` sends batched JMAP requests — `list` and `search` combine Email/query + Email/get in one round-trip via `#ids` back-reference
- `search` also fetches Mailbox/get in the same batch to resolve mailbox names
- `_mailbox_map()` caches mailbox id→name; `_resolve_mailbox` uses the cache
- `cat` (default): fetches parsed body via `Email/get` with `fetchTextBodyValues`/`fetchHTMLBodyValues`; prefers `text/plain` if ≥ 200 chars, otherwise falls back to HTML → `strip_html()`
- `cat --raw`: downloads raw RFC 2822 blob via `downloadUrl` from session; single ID only
- `cat` warns to stderr if any body part was truncated (`isTruncated: true`)
- `parse_since()`: converts `24h`/`7d`/`2w` → ISO 8601 UTC; injected as `"after"` into JMAP filter
- `maybe_decode_qp()`: heuristic QP decoder; detects `=XX` or `=\r?\n` soft line breaks
- `strip_html()`: removes style/script/head blocks, converts block tags (p/div/tr/td/th/li/hN) to newlines, strips remaining tags, unescapes HTML entities, strips zero-width Unicode spacers
- All timestamps converted to local timezone via `.astimezone()`
- `httpx.Client` is not explicitly closed — acceptable for a single-shot CLI
- Output: plain text tables, readable by both humans and LLMs

## Syncing the skill

After any change to `fmdig.py` or `SKILL.md`, sync to the installed skill directory:

```zsh
cp fmdig.py ~/.claude/skills/fmdig/fmdig.py
cp SKILL.md ~/.claude/skills/fmdig/SKILL.md
```

## Before committing

1. Re-read `fmdig.py` and flag any obvious bugs, dead code, or inconsistencies.
2. Verify `CLAUDE.md`, `README.md`, `SKILL.md` match current CLI flags and behaviour.

## Tests

```zsh
uv run --group dev pytest        # run all tests + coverage report
uv run --group dev pytest -v     # verbose
```

Tests live in `tests/test_fmdig.py`. Cover pure functions (`parse_since`, `maybe_decode_qp`, `strip_html`) and `JMAP.search` filter construction via mocked httpx. No network calls. Coverage is reported automatically via `pytest-cov`.

## Linting / type checking

```zsh
uvx ty check fmdig.py
uvx ruff check fmdig.py
```
