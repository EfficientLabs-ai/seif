# Efficient Labs observability and backup runbook

Status: draft

## Current service inventory

- `seif-redis`: Redis L1, bound to 127.0.0.1:6379.
- `atmos-secure-bridge`: PM2, Node 22.22.3, 127.0.0.1:4099.
- `stratos-agent-upstream`: PM2, Node 22.22.3, 127.0.0.1:5001.
- `atmos-mesh-origin`: PM2, Node 22.22.3.
- Langfuse stack: web, worker, Postgres, Redis, ClickHouse, MinIO.
- LiteLLM stack: app and Postgres.
- Presidio analyzer/anonymizer.

## Health checks

```bash
docker exec seif-redis redis-cli ping
curl -fsS http://127.0.0.1:4099/health
curl -fsS http://127.0.0.1:5001/health
pm2 list --no-color
docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}'
```

## PM2 discipline

```bash
pm2 save
pm2 startup
pm2 logs --lines 100
pm2 describe atmos-secure-bridge
pm2 describe stratos-agent-upstream
pm2 describe atmos-mesh-origin
```

## Alert thresholds

- PM2 process offline: P0.
- Bridge health fails: P0.
- Upstream health fails: P1 if bridge fallback works, P0 if no fallback.
- Redis unavailable: P1 for local work, P0 once promoted to production state.
- Disk above 80 percent: P1, above 90 percent: P0.
- Backup missing for 24 hours: P0 after live billing.
- Restore drill older than 7 days: P1 after live billing.

## Missing before launch

- Off-host encrypted backup target.
- Postgres state plane.
- WAL archive policy.
- PM2 log rotation configuration.
- SEIF backup receipt command.
- Incident runbook with rollback owner and communication path.
