# Docker Deployment Modes

TrendRadar should use one of these modes at a time.

## 1. Development Mode

Use `docker/docker-compose.yml`.

Characteristics:
- Mounts `../trendradar` into `/app/trendradar`
- Mounts `../config` and `../output`
- Best for quick iteration and debugging

Tradeoff:
- Container runtime can drift from image dependencies
- Good for local/dev, not ideal for long-term production

## 2. Production Mode

Use `docker/docker-compose-build.yml`.

Characteristics:
- Builds image from repo source
- Does not mount `../trendradar`
- Mounts only config/output
- Best for stable long-running deployment

Tradeoff:
- Slower to update
- Requires rebuild on code changes

## Recommendation

- Local development: `docker-compose.yml`
- Pure image-based long-running deployment: `docker-compose-build.yml`

## Current Project Standard

For this workspace, the operational standard is:

- Remote deploy entry: `deploy_remote.cmd` / `tools/deploy_remote.ps1`
- Current default compose file in that script: `docker/docker-compose.yml`

Reason:
- The current cloud workflow prefers bind-mounted hot reload so UI / report-layer changes can be pushed quickly without rebuilding the image every time.

Implication:
- `docs/deployment-modes.md` describes the cleaner mode split in principle
- `tools/deploy_remote.ps1` describes what the project actually does today
- When these conflict, treat the script as the runtime truth source

Do not mix these modes for the same long-lived server unless you intentionally switch and understand the consequences.
