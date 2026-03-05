# fmdig

Read-only Fastmail CLI via the JMAP API. Single Python file, runs with [uv](https://github.com/astral-sh/uv).

Designed to be used as a [Claude Code skill](https://docs.claude.ai/en/docs/claude-code/skills) — Claude will automatically reach for it when you ask about your email.

## Claude Code skill

Install the skill globally so Claude picks it up in any project:

```zsh
git clone https://github.com/youruser/fmdig ~/.claude/skills/fmdig
```

That's it. Claude Code loads skills from `~/.claude/skills/` automatically. Store your token first:

```zsh
~/.claude/skills/fmdig/fmdig.py login
```

Then just ask Claude about your email in natural language:

> "find emails from GitHub this week"
> "any shipping notifications today?"
> "show my inbox"

Claude will invoke the skill, run the appropriate `fmdig.py` command, and summarize the results.

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

Dependencies (`httpx`, `keyring`) are declared inline and installed automatically by uv on first run.

## Installation

```zsh
git clone https://github.com/youruser/fmdig
chmod +x fmdig/fmdig.py
ln -s "$PWD/fmdig/fmdig.py" ~/.local/bin/fmdig
```

Or just run it directly:

```zsh
./fmdig.py folders
```

## Authentication

Get a Fastmail API token at **Settings → Privacy & Security → API Tokens**. Scope: `Mail (read-only)` is enough.

Store it in the system keyring (macOS Keychain, GNOME Keyring, KWallet):

```zsh
fmdig login
```

Or pass it as an environment variable (takes priority over keyring):

```zsh
export JMAP_TOKEN=your-token-here
```

## Usage

```
fmdig login                           save API token to system keyring
fmdig folders                         list mailboxes with unread/total counts
fmdig list <mailbox> [--limit N]      list emails (default: 50)
              [--preview]             show server-generated snippet per email
fmdig search --query '<json>'         search with JMAP FilterCondition JSON
             [--limit N] [--since AGO] [--preview]
fmdig cat <id> [<id2> ...]            show parsed email(s) (headers + body text)
fmdig cat <id> --raw                  dump raw RFC 2822 (single ID only)
              [--max-body KB]         max body size to fetch, default 100 KB
```

### Search examples

JMAP filter fields: `text`, `from`, `to`, `subject`, `after`, `before`, `hasAttachment`, `hasKeyword`, `notKeyword`. Multiple fields in one object are ANDed.

```zsh
fmdig search --query '{"text": "invoice"}' --since 7d
fmdig search --query '{"from": "github.com"}' --since 24h
fmdig search --query '{"notKeyword": "$seen"}' --limit 20

# OR / NOT operators
fmdig search --query '{"operator":"OR","conditions":[{"from":"github.com"},{"from":"gitlab.com"}]}'
fmdig search --query '{"operator":"NOT","conditions":[{"from":"noreply"}]}' --since 7d
```

Note: `--preview` shows a server-generated 256-char snippet. For HTML-only emails this is often navigation noise — use `cat` to read the actual body.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `JMAP_TOKEN` | — | API token (overrides keyring) |
| `JMAP_SESSION_URL` | `https://api.fastmail.com/jmap/session` | JMAP session endpoint |

## License

GPL-3.0. See [LICENSE](LICENSE).
