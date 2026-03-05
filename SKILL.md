---
name: fmdig
description: Read Fastmail email via fmdig CLI. Trigger when user asks about their email inbox, letters, messages — "покажи почту", "что пришло", "есть письма от", "найди письмо", "проверь инбокс", "show my email", "check inbox", "any emails from", "find email about", or asks to read/search specific emails.
argument-hint: "[folders | list <mailbox> | search --query '<json>' | cat <id>]"
allowed-tools: Bash
---

Use `${CLAUDE_SKILL_DIR}/fmdig.py` to answer questions about email.

`fmdig.py` uses a `uv` shebang — run it directly (`./fmdig.py`), not with `python`. Requires [uv](https://docs.astral.sh/uv/) to be installed. Dependencies (`httpx`, `keyring`) are installed automatically on first run.

## Commands

```bash
# list mailboxes with counts
${CLAUDE_SKILL_DIR}/fmdig.py folders

# list emails in a mailbox (default limit 50)
${CLAUDE_SKILL_DIR}/fmdig.py list Inbox --limit 20
${CLAUDE_SKILL_DIR}/fmdig.py list Inbox --since 7d

# search with JMAP FilterCondition JSON
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"text": "invoice"}'
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"from": "boss@company.com"}'
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"subject": "meeting"}' --since 7d

# read one or more emails (parsed text, default)
${CLAUDE_SKILL_DIR}/fmdig.py cat <id>
${CLAUDE_SKILL_DIR}/fmdig.py cat <id1> <id2> <id3>

# read raw RFC 2822
${CLAUDE_SKILL_DIR}/fmdig.py cat <email-id> --raw
```

## JMAP FilterCondition fields

Useful fields for `--query`:
- `"text"` — full-text search across all fields
- `"from"` — sender address substring
- `"to"` — recipient address substring
- `"subject"` — subject substring
- `"after"` / `"before"` — ISO 8601 datetime strings (use `--since` instead when possible)
- `"hasAttachment": true` — emails with attachments
- `"inMailbox"` — mailbox ID (use `folders` to get IDs)
- `"hasKeyword": "$flagged"` — starred/flagged emails
- `"hasKeyword": "$seen"` / `"notKeyword": "$seen"` — read / unread

Multiple fields in one object are ANDed together.

### OR / AND / NOT operators

```bash
# OR: emails from github OR gitlab
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"operator":"OR","conditions":[{"from":"github.com"},{"from":"gitlab.com"}]}'

# NOT: exclude newsletters (no $seen unread, not from noreply)
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"operator":"NOT","conditions":[{"from":"noreply"}]}'

# AND with explicit operator (same as flat object, but composable)
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"operator":"AND","conditions":[{"from":"github.com"},{"hasAttachment":true}]}'
```

### Keyword shortcuts for importance/category

```bash
# unread only
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"notKeyword":"$seen"}'

# flagged/starred only
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"hasKeyword":"$flagged"}'

# unread AND flagged
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"notKeyword":"$seen","hasKeyword":"$flagged"}'
```

Note: `--preview` shows a server-generated 256-char snippet from the start of the email. For HTML-only emails this is often navigation/header noise, not the actual content. Use `cat` to read the body.

## --since shorthand

`--since` accepts `24h`, `7d`, `2w` and injects an `"after"` condition into the filter:

```bash
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"text":"invoice"}' --since 24h
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"notKeyword":"$seen"}' --since 7d
```

## Workflow

1. If the user asks about a specific mailbox — `list <mailbox>`
2. If the user wants to find something — `search --query '{…}'`
3. If the user wants to read an email — `cat <id>` (get id from list/search output)
4. If the user asks what mailboxes exist — `folders`

Prefer `search` over `list` when user describes content, sender, or time range.
When reading email with `cat`, parse headers and body to answer the user's question naturally.
Use `--raw` only if the user explicitly asks for raw/original message format.

## Excluding Spam and Trash from search

`search` queries all mailboxes by default, including Spam and Trash.

When doing a **general search** (user didn't ask to search spam/trash), exclude junk folders:

1. Run `${CLAUDE_SKILL_DIR}/fmdig.py folders` to get mailbox list
2. Find IDs of mailboxes named Spam, Trash, Junk, Deleted Items (case-insensitive)
3. Add `"inMailboxOtherThan": ["<id1>", "<id2>", ...]` to the `--query` JSON

Example — exclude Spam and Trash:
```bash
# first get IDs:
${CLAUDE_SKILL_DIR}/fmdig.py folders

# then search with exclusion:
${CLAUDE_SKILL_DIR}/fmdig.py search --query '{"text":"invoice","inMailboxOtherThan":["<spam_id>","<trash_id>"]}'
```

If the user explicitly asks to search in spam or trash, skip this step and use `inMailbox` to target that folder directly.
