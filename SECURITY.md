# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in EvoMind, **please do not open a public issue.**

Instead, report it privately by emailing **harsh.d.5382@gmail.com** with:

- a description of the issue,
- steps to reproduce (a proof of concept if possible),
- the potential impact, and
- any suggested fix.

You can expect an acknowledgement within a few days. Please give us a reasonable
window to investigate and release a fix before any public disclosure.

## Secrets & API keys

EvoMind talks to external LLM providers and databases, so handle credentials carefully:

- **Never commit `.env`.** It is git-ignored — keep it that way. Only `.env.example` (with empty
  placeholders) belongs in the repo.
- If a key is ever committed or otherwise exposed, **rotate it immediately** (e.g. revoke and
  regenerate NVIDIA / Anthropic / OpenAI keys in the provider dashboard).
- Use local/offline options where you can — `EMBEDDING_PROVIDER=local` (sentence-transformers) and
  Ollama need no external keys.

## Deployment hardening

The default credentials shipped for local development (`neo4j` / `evomind123`, `evomind` / `evomind`
for Postgres) are **for local use only**. Before exposing EvoMind on any network:

- Change all default database and Neo4j passwords.
- Do not expose Postgres, Redis, Qdrant, or Neo4j ports publicly.
- Note that the REST API is currently **open (no auth)**. Put it behind authentication
  (JWT/OAuth/reverse proxy) before deploying anywhere reachable by untrusted users.

## Supported Versions

This project is in active early development; security fixes are applied to the latest `main`. Please
track the latest release.
