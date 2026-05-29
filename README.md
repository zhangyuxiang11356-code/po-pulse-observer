# PO | Pulse Observer

> AI-powered trend radar for news, RSS, X, Reddit, and public web signals.

PO | Pulse Observer is a deployable trend-observation system based on the open-source [TrendRadar](https://github.com/sansan0/TrendRadar) project. It collects public signals, filters and clusters them with AI, and renders a daily HTML briefing.

This repository is the clean open-source edition. It includes public source configuration, prompts, templates, Docker files, and deployment scripts. It does not include private keys, cookies, tokens, runtime logs, or personal cloud credentials.

## What It Does

- Collects configured news, RSS, X, and Reddit sources
- Applies keyword filtering and AI-assisted analysis
- Generates a daily HTML report
- Supports Docker deployment
- Supports optional AI analysis through `AI_API_KEY`
- Supports optional X login state through a local `secrets/x_storage_state.json`

## Included Sources

The default source list is intentionally public and editable:

- News and RSS sources live in `config/config.yaml`
- X watchlist lives under `social_media.sources[x-watchlist]`
- Reddit communities live under `social_media.sources[reddit-watchlist]`
- AI prompts live under `config/ai_analysis_prompt.txt` and `config/ai_filter/`

You can keep the default watchlist, delete it, or replace it with your own.

## Quick Start

### Local Python

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m trendradar
```

### Docker

```bash
cd docker
cp .env.example .env
docker compose up -d --build
```

Put real runtime secrets only in `docker/.env` or environment variables. Do not commit them.

## AI Configuration

AI analysis is optional. Configure it through environment variables or `docker/.env`:

```text
AI_API_KEY=
AI_MODEL=
AI_API_BASE=
```

`config/config.yaml` keeps `ai.api_key` empty by default. Using environment variables is recommended.

## X Login State

X collection can work better with a browser storage state file:

```text
secrets/x_storage_state.json
```

This file contains cookies and must never be committed. The repository includes helper scripts in `tools/` for exporting and filtering a local browser login state.

## What Is Not Included

- Real AI keys
- GitHub tokens
- SSH private keys
- X cookies or login state
- Proxy subscriptions
- Runtime output under `output/`
- Personal cloud deployment records

## Attribution

This project is a customized derivative of [TrendRadar](https://github.com/sansan0/TrendRadar). The original project is licensed under GPL-3.0.

## License

GPL-3.0. See [LICENSE](LICENSE).
