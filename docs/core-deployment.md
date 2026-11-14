# Core deployment on Dozor

Lineage's engine uses Compose project `lineage-core`, service `core`, at
`/srv/apps/lineage-core/compose.yml`. Its private audience, host network,
loopback API on port 28347 and existing database are retained. Almaz's public
read-only allowlist remains the boundary for write and operator routes.

The independent `core` workflow job builds a labels-only wrapper from
`deploy/archive-core.env`. It compares the live version and last successful
core deployment with the pin and wrapper. `CORE_DEPLOY_ENABLED=true` enables
this lane; `HOMELAB_CORE_DEPLOY_KEY` is separate from the frontend key. Both use
`DEPLOY_TARGET` and the existing pinned host key. Frontend deployment waits for
any required core upgrade to succeed.

## Backup protocol

The measured 8 GB compressed backup took approximately 22 minutes on November
14, exceeding the fleet receiver's 120-second pre-deploy hook. Do not increase
that limit for unrelated applications or skip the backup.

Install the reviewed `scripts/core_backup.py`, a reviewed fleet-deploy
`receiver.py`, and the host-owned `profile.json` in `/srv/deploy/lineage-core`.
The core key's restricted forced command runs `core_backup.py` as `patrick`.
It handles only `prepare-backup REVISION` itself; all other commands pass to
the receiver's existing parser. Preparation takes the same application lock,
checks current main before and after the dump, validates the archive's table
of contents, and writes an atomic receipt with the revision, start time, byte
count and SHA-256. PostgreSQL and the client both have bounded deadlines.
Credentials remain in host-owned runtime files, outside Git and CI output.

The workflow prepares the backup after receiving the image and before deploying.
The receiver's fixed `pre_deploy_command` invokes
`/usr/bin/python3 /srv/deploy/lineage-core/core_backup.py --check`.
That gate requires current main, an archive started within the last hour,
matching size and hash, and a readable archive table of contents. It consumes
the receipt before migration; a failed migration or a second deployment needs
a new preparation. A partial or failed backup never creates a usable receipt.
The gate runs under the receiver lock. Backups remain in
`/srv/recovery/backups/lineage-core`; this path is local recovery storage,
not an off-host backup claim. Retain the pre-upgrade dump through rollout
acceptance. Review disk usage before subsequent deployments; this script does
not automatically delete recovery archives.

A fresh backup is a disaster-recovery point, not a promise that later source
imports are included. Do not run metadata imports during deployment. For a
restore, stop all writers first and restore into a separate database, validate
it, then select it deliberately. Never restore over a running production DB.

## Migration and rollback

The receiver profile runs the candidate `operator migrate` before activating
`core`. Migrations must satisfy Arkhiv's additive compatibility contract.
First rehearse the upgrade on a restored database and verify that the old image
still serves it. The receiver's normal rollback changes the image, not data.
Keep the pre-Compose hand-run container and the pre-upgrade Compose file until
the rollout and rollback checks pass; do not restart both engines on port 28347.

After activation, check `/api/version` for the pinned version and required
source modules, artist/calendar requests, playback resolution and an audio
range request. Check that POST/PUT/DELETE and operator/download routes remain
blocked at the public hostname. Browser playback is separate evidence.
