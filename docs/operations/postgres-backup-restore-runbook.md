# Postgres backup and restore runbook

Status: draft

## Baseline policy

- Nightly custom-format `pg_dump`.
- Continuous WAL archiving for point-in-time recovery.
- Encrypted off-host backup copy.
- Weekly restore drill.
- Monthly disaster recovery rehearsal.
- SEIF backup receipt for each backup and restore drill.

## Roles

- `app_user`: least-privilege application access.
- `migration_user`: schema migrations only.
- `readonly_analytics_user`: read-only reporting.
- `backup_user`: backup/replication permissions only.

## Backup command template

```bash
pg_dump --format=custom --no-owner --no-acl --file "$BACKUP_DIR/efficientlabs-$(date -u +%Y%m%dT%H%M%SZ).dump" "$DATABASE_URL"
```

## Restore drill template

```bash
createdb efficientlabs_restore_drill
pg_restore --clean --if-exists --no-owner --dbname efficientlabs_restore_drill "$BACKUP_FILE"
psql efficientlabs_restore_drill -c 'select count(*) from organizations;'
```

## Launch blocker

Live Stripe billing is blocked until a restore drill succeeds from an encrypted off-host backup and the drill receipt is written to SEIF.
