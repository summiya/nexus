# Nexus File Upload Event Routing

## RF-04 PostgreSQL / pgvector prerequisites

`infra/postgres/Dockerfile` adds pgvector 0.8.7 to the exact existing PostgreSQL
16.15 / Alpine 3.24.1 base, pinned by multi-architecture digest
`sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`.
Both AMD64 and ARM64 manifests identify the same PostgreSQL/Alpine release. The
source is pinned to upstream commit `f37c13f68b57d2c3472b2214fbcff699d6d34876`
and archive SHA-256 `83d673c3b287cddbf3879f86215f043f2c2b56c69d37b2a77504910db1ed6e56`.
Compilation uses that base's `/usr/local/bin/pg_config`, headers and PGXS with
`OPTFLAGS=""`; no second Alpine PostgreSQL installation is introduced.

Build tools exist only in the builder. The final stage starts from the identical
pinned base and copies only extension artifacts, preserving PostgreSQL binaries,
runtime libc/ICU, configuration, UID/GID, entrypoint and PGDATA. The existing
Compose `postgres-data` mapping to `/var/lib/postgresql/data` is unchanged. There
are no added startup SQL/init scripts or automatic migrations. As with the
original upstream entrypoint, an empty directory would initialize a new cluster:
the operator must therefore verify the existing volume and cluster identity
before starting a replacement. Never substitute an empty volume or run initdb,
pg_upgrade, a collation refresh, volume deletion/pruning or a data-directory reset.

### Automated validation never uses the existing database

```bash
make postgres-check
make backend-integration-check
make backend-check
make docker-check
pre-commit run --all-files
```

`test-image.sh` generates a fresh `nexus-rf04-test-*` project. Backend/integration
checks use only the standalone `infra/postgres/compose.test.yml`, `.env.example`,
literal test database endpoints and anonymous volumes; root `.env`, inherited
Compose project/file defaults, host data mounts, external/named volumes and
published ports cannot select the existing database. No production Compose
service is started. The image test allocates its own labeled network/volumes,
applies the pre-RF-04 schema, and seeds synthetic Users, Files, Documents and RBAC.
It checks a clean base-to-custom image replacement on that synthetic cluster,
verified logical backup/restore, ownership/grants/constraints/sequences and RF-04
vector functionality. The base PostgreSQL/libc/ICU/entrypoint hashes must match.

Test scripts only stop their own resources and retain containers, disposable
volumes and protected temporary artifacts for inspection; they do not run Docker
removal, down or prune commands. CI first checks out the code and builds/tests the
image, then explicitly launches a health-checked PostgreSQL container with a new
anonymous volume. It does not attempt to use a not-yet-built job service image.

### Manual backup and verified restore (operator authorization required)

The following procedure is documentation, **not an automatic test or deployment**.
Image correction approval does not authorize a live backup, restart or migration.
Use PostgreSQL 16.15 client tools, authenticated libpq service entries outside
source control, and a maintenance window. `nexus-live` must identify the reviewed
existing server/application database; `nexus-restore` must identify a fresh,
non-public disposable server, database `postgres`, and a bootstrap superuser name
absent from the source role list. Confirm these identities before any restore.
Inventory all databases, non-default tablespaces, locale/collation settings,
installed extensions, volume mapping, image ID, migration revision, roles and
writers. Non-default tablespaces require a reviewed restore-path mapping first.

1. Quiesce all application/worker/external writers and role changes. Keep the
   source server running to take the final consistent logical backups. Verify
   the writer shutdown; an idle-session check alone is not a write fence.
2. Capture backups with owners and grants intact. Repeat the custom dump for
   every application database in the inventory. Protect/encrypt the directory
   and keep a verified off-host copy: globals can contain credential hashes.

```bash
set -euo pipefail
umask 077
NEXUS_BACKUP_DIR=/secure/backups/nexus/REVIEWED_UTC_TIMESTAMP
mkdir -p "$NEXUS_BACKUP_DIR"
PGSERVICE=nexus-live psql -X -v ON_ERROR_STOP=1 -Atc \
  'SELECT system_identifier FROM pg_control_system()' > "$NEXUS_BACKUP_DIR/source-cluster-id"
PGSERVICE=nexus-live pg_dumpall --globals-only --file="$NEXUS_BACKUP_DIR/globals.sql"
PGSERVICE=nexus-live pg_dump --format=custom --dbname=nexus --file="$NEXUS_BACKUP_DIR/nexus.dump"
pg_restore --list "$NEXUS_BACKUP_DIR/nexus.dump" > "$NEXUS_BACKUP_DIR/archive-list.txt"
openssl dgst -sha256 "$NEXUS_BACKUP_DIR/globals.sql" "$NEXUS_BACKUP_DIR/nexus.dump" \
  > "$NEXUS_BACKUP_DIR/backup.sha256"
```

3. Verify restore-target identity is different from the live cluster and that
   application database `nexus` does not already exist. Do not use `--clean`,
   `--no-owner` or `--no-acl` to suppress errors. A non-colliding bootstrap role
   permits fail-fast restoration of the original SQL roles.

```bash
PGSERVICE=nexus-restore psql -X -v ON_ERROR_STOP=1 -Atc \
  'SELECT system_identifier FROM pg_control_system()' > "$NEXUS_BACKUP_DIR/restore-cluster-id"
if cmp -s "$NEXUS_BACKUP_DIR/source-cluster-id" "$NEXUS_BACKUP_DIR/restore-cluster-id"; then
  echo 'Refusing to restore onto the source cluster' >&2; exit 1
fi
test "$(PGSERVICE=nexus-restore psql -X -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM pg_database WHERE datname='nexus'")" = 0
PGSERVICE=nexus-restore psql -X -v ON_ERROR_STOP=1 --file="$NEXUS_BACKUP_DIR/globals.sql"
PGSERVICE=nexus-restore pg_restore --exit-on-error --create --dbname=postgres \
  "$NEXUS_BACKUP_DIR/nexus.dump"
```

4. Point a separate service `nexus-restored` at the restored `nexus` database.
   Compare **all** public table contents, not only counts. The following hashes
   stream canonical sorted rows without printing private values. Keep writers
   fenced throughout the comparison; review any mismatch before proceeding.

```bash
fingerprint_tables() {
  local service="$1" tables table
  tables=$(PGSERVICE="$service" psql -X -v ON_ERROR_STOP=1 -Atc \
    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
  test -n "$tables"
  while IFS= read -r table; do
    case "$table" in ''|*[!a-z0-9_]*) echo 'Review nonstandard table name' >&2; return 1;; esac
    printf '%s\n' "$table"
    PGSERVICE="$service" PGOPTIONS='-c timezone=UTC -c datestyle=ISO,MDY' \
      psql -X -q -v ON_ERROR_STOP=1 -c \
      "COPY (SELECT to_jsonb(t) FROM public.\"$table\" t ORDER BY to_jsonb(t)::text) TO STDOUT" \
      | openssl dgst -sha256
  done <<< "$tables"
}
fingerprint_tables nexus-live > "$NEXUS_BACKUP_DIR/source-tables.sha256"
fingerprint_tables nexus-restored > "$NEXUS_BACKUP_DIR/restored-tables.sha256"
cmp "$NEXUS_BACKUP_DIR/source-tables.sha256" "$NEXUS_BACKUP_DIR/restored-tables.sha256"
```

   Also compare SQL role attributes/memberships, table/schema/sequence owners,
   grants/default privileges, PK/FK/unique/CHECK definitions and validation flags,
   sequence `last_value`/`is_called`, and database locale/encoding/collation. Use
   `pg_dump --data-only` to retain sequence setval state and a schema-only dump
   for ownership/privileges. Logical restores may normalize CHECK-expression
   cast syntax; review semantic differences rather than ignoring constraints.
   Exercise allowed/denied File/RBAC operations and tenant FK failures on the
   **restored disposable** database, and verify sequence continuation there.
   Do not restore into, run destructive probes on, or mount the live data volume
   to perform these checks. Actual successful restoration, checksums and semantic
   checks are required; `pg_restore --list` alone is not restore verification.

### Operator-controlled image replacement and separate migration

After the verified backup/restore and explicit deployment approval, record the
old image ID and the tested custom image ID/digest. Verify the target is the
reviewed existing `nexus` Compose project, the `nexus_postgres-data` volume and
the same `/var/lib/postgresql/data` mapping. Keep writers fenced. Cleanly stop
only the old PostgreSQL process, and ensure it has exited before starting the
replacement; never run two servers against one data directory.

The reviewed operator commands, from the deployed repository/configuration, are:

```bash
docker compose --project-name nexus --file docker-compose.yml stop postgres
docker compose --project-name nexus --file docker-compose.yml up -d --no-deps --no-build postgres
```

Verify readiness, PostgreSQL/Alpine version, unchanged cluster system identifier,
existing data, locale/collation, permissions and that initialization was skipped.
Abort if the volume mapping, cluster identity, version or expected data differs.
The replacement image makes the extension **available**, not enabled. Do not use
init scripts or an automatic startup migration. With writers still fenced,
extension privileges/availability reviewed and a DDL lock window scheduled, apply
only the approved migration `alembic upgrade 20261103_0020` as a separate explicit
operator step. Verify extension version 0.8.7, schema constraints and source data
before reopening writers. Do not upgrade/relabel existing vectors or begin RF-05.

### Rollback boundaries

Before extension/schema activation, an image-only rollback can cleanly stop the
replacement and restart the recorded old image on the same intact data volume.
Once `vector` objects exist, the original image lacks their library: do not assume
it is a functional rollback. Prefer a tested extension-capable image, or execute
an approved schema/recovery plan. RF-04 downgrade discards new embedding rows and
preserves the shared extension; never apply it blindly. A backup recovery must
restore into separate recovery storage, retain the original volume, and reconcile
any writes committed after the backup before routing users to recovered data.
No reset, volume deletion/pruning, unclean directory copy or automatic downgrade
is part of this procedure.

This repository currently has no PostgreSQL-server deployment template. For an
existing Azure Database for PostgreSQL Flexible Server, operators must confirm
PostgreSQL 16 and an available compatible pgvector version, add `vector` to
`azure.extensions` **without replacing other allowlisted extensions**, and verify
the migration role can create it in the target database. Azure's supported version
need not equal the local image's version, but the vector type and `vector_norm`
must be available and migration tests must pass on that deployed version. Do not
grant extension-management or superuser privileges to the application role.

Migration `20261103_0020` runs `CREATE EXTENSION IF NOT EXISTS vector`; it fails if
the extension is unavailable or not permitted. Schedule the new parent unique-key
build for an appropriate lock window and take a database backup before migration.
There is no embedding backfill or HNSW index build. A schema downgrade drops new
embedding data but preserves all source tables and the shared extension. After
the new database accepts writes, failback requires a data-reconciliation plan;
simply starting the old volume can lose newly committed writes.

References: [pgvector build settings](https://github.com/pgvector/pgvector/blob/v0.8.7/Makefile),
[PostgreSQL logical backups](https://www.postgresql.org/docs/16/backup-dump.html),
[global-role backups](https://www.postgresql.org/docs/16/app-pg-dumpall.html),
[Azure extension prerequisites](https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-use-pgvector).

## Provider credential Key Vault

`provider-credentials.bicep` deploys the dedicated model-provider credential
vault. The module explicitly enables Azure RBAC authorization, soft delete, and
purge protection, and grants the existing Nexus API Managed Identity only the
built-in Key Vault Secrets Officer role at vault scope. It does not create or
store application credentials.

Compile it through `make infra-check`, then deploy it at resource-group scope
with reviewed values based on `provider-credentials.example.bicepparam`.
Production supplies `AZURE_KEY_VAULT_URL` and optional user-assigned Managed
Identity client ID through deployment configuration. Network restriction/private
endpoints and Key Vault diagnostic audit logging are explicit production
hardening follow-ups.

The local Fernet adapter is not a production alternative. Generate its
developer key outside source control using the command documented in
`.env.example`; Docker Compose consumes that environment value and does not
provide a usable default.

This directory contains the EPIC 05 Phase 12 Azure infrastructure for routing
committed Nexus File blobs into a durable queue. The worker is deployed as a
separate process:

```text
File Blob container
    -> Event Grid system topic
    -> Nexus File event subscription
    -> Service Bus queue
    -> dedicated Phase 13 worker (deployed separately)
```

No template in this directory creates a worker, database resource, Redis
resource, or application runtime dependency.

## Launch topology and capacity

The production launch configuration is:

```text
Service Bus Premium
1 partition
1 Messaging Unit
80-GiB file-upload-completions queue
```

`premiumMessagingPartitions` is an immutable namespace-creation choice and is
required explicitly. Supported values are 1, 2, or 4. Total Messaging Units
must be a compatible multiple of the partition count. The checked-in example
selects one partition and one MU; it does not rely on the Azure default.

Scale MUs from measured CPU, memory, queue depth, processing lag, and message
throughput. Registered-user count is not a messaging-capacity metric. Changing
the partition count later requires a new namespace and a controlled
infrastructure migration; it does not require a File domain redesign.

Current partitioned-Premium differences must be reconsidered before selecting
two or four partitions:

- JMS is not supported on partitioned Premium namespaces;
- Standard-to-Premium migration cannot target a partitioned Premium namespace;
- batches with distinct `SessionId` or `PartitionKey` values are unsupported;
- current Geo-DR documentation prohibits pairing partitioned and
  non-partitioned namespace configurations, so peer compatibility must be
  revalidated against the chosen resource model;
- regional availability must be confirmed.

Messaging Units are distributed evenly across the configured partitions. The
one-partition launch may scale MU capacity without changing Nexus application
code, but changing the partition count remains a namespace migration.

At production deployment review, record the selected region, date, currency,
regional MU-hour price, and applicable agreement or retail rate. Compare:

```text
1-partition / 1-MU estimate = regional MU-hour price x about 730 hours
2-partition / 2-MU estimate = regional MU-hour price x about 730 x 2
```

These are estimates rather than invoice prices. Do not commit a stale global
dollar rate to the architecture.

Operational references:

- [Premium partitions and limitations](https://learn.microsoft.com/azure/service-bus-messaging/enable-partitions-premium)
- [Premium Messaging Units](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-premium-messaging)
- [Azure retail pricing data](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices)

## Explicit system-topic ownership

Azure permits one Event Grid system topic per source. Treat the storage-account
system topic as shared source infrastructure: Defender for Storage, security,
audit, or operational consumers may add their own subscriptions later.

There is no deployment-time discovery or implicit create-if-missing behavior.
Choose one mode explicitly:

### Existing-system-topic mode

Supply the full existing system-topic resource ID, subscription, resource
group, and name to `file-upload-events.bicep`. The template validates that the
components identify the same resource. It references the topic and creates only
the Nexus-owned File event subscription. It never adopts, replaces, or deletes
the existing topic.

The existing topic must already have a system-assigned Managed Identity. A
missing topic or identity causes deployment to fail rather than silently
creating or weakening infrastructure.

The pipeline also resolves the configured existing storage account and fails
closed unless the selected topic has `Microsoft.Storage.StorageAccounts` as its
topic type and that exact account resource ID as its source. The selected topic
must expose a usable system-assigned Managed Identity principal. The Service
Bus resource location is derived directly from the source storage account; it
is not an independent deployment parameter. These deployment guards prevent a
different storage account, an unusable topic identity, or an accidental
cross-region pipeline from receiving Nexus queue permissions.

### New-system-topic mode

Only after confirming that the storage account has no system topic, deploy
`shared-storage-system-topic.bicep`. That deployment explicitly owns creation of
the new shared topic and its system-assigned identity. Pass its `resourceId`
output to `file-upload-events.bicep`.

Keep the shared-topic deployment lifecycle separate from the File subscription
lifecycle. Removing the File pipeline must remove only the Nexus subscription,
not a topic used by other consumers.

## Shared system-topic permission boundary

Restrict permission to create or modify event subscriptions on the shared
system topic to the deployment identity and a small audited operations group.
An event subscription can request delivery using the topic's Managed Identity;
unrestricted subscription creation could therefore direct that trusted
identity into `file-upload-completions` or another authorized destination.

Review custom roles and broad Event Grid Contributor assignments for actions
such as:

```text
Microsoft.EventGrid/systemTopics/eventSubscriptions/write
Microsoft.EventGrid/systemTopics/eventSubscriptions/delete
```

Do not grant application identities permission to create event subscriptions.
Log and review subscription changes as security-sensitive control-plane events.

## Routing and identity

The Nexus subscription delivers exactly one CloudEvents 1.0 event per Service
Bus message and includes only:

```text
Microsoft.Storage.BlobCreated
subject begins with:
/blobServices/default/containers/<file-container>/blobs/files/
```

The subject comparison is case-sensitive. Event Grid deliberately does not
filter `data.api` or `data.blobType`; the Phase 11 mapper validates `PutBlob`,
`PutBlockList`, and `BlockBlob` and rejects malformed semantic input.

The selected system-topic identity receives only:

- Azure Service Bus Data Sender at the File queue;
- Storage Blob Data Contributor at the Event Grid dead-letter container.

Azure RBAC assignments can take several minutes to become effective after ARM
reports the role-assignment resources as successful. In a new environment, the
narrow queue/container assignments may therefore exist before Event Grid can
use them. Do not add sleeps, broader roles, or local credentials. Wait for RBAC
propagation and rerun the same idempotent Bicep deployment if event-subscription
creation encounters a transient authorization failure.

The Service Bus namespace disables local authentication, requires TLS 1.2 or
later, denies ordinary public-network traffic through its firewall, and enables
trusted Microsoft service access for Event Grid. Event Grid cannot deliver to
Service Bus through a private endpoint. Future workers should use private
networking where appropriate.

## Duplicate detection and delivery identity

The queue enables a ten-minute duplicate-detection window. Event Grid sets the
Service Bus `MessageId` to an internal system ID that Microsoft documents as
stable across redelivery of the same event; `aeg-output-event-id` retains the
original Event Grid event ID.

Duplicate detection is load reduction only. `(source, event_id)` is transport
correlation, not a correctness boundary. Phase 14 must enforce complete File
business identity, immutable ownership, and `INV-REL-004` across redelivery,
DLQ replay, and reconciliation.

## File worker authorization

Phase 13 recommends a user-assigned Managed Identity for the independently
scaled File worker. `fileWorkerPrincipalId` is optional because this routing
deployment does not create that identity. When it is empty, no worker role is
created. When the worker deployment has provisioned the identity, rerun the
same idempotent deployment with its principal ID to grant Azure Service Bus
Data Receiver on `file-upload-completions` and Storage Blob Data Reader on the
configured File container. Both assignments are scoped to the individual
queue/container rather than their parent namespace/account.

The worker must reach the default-deny namespace through an approved private
network path, preferably VNet integration with a Service Bus private endpoint
and private DNS. Do not enable local authentication or broaden public network
access for worker convenience.

For one partition, uniqueness is `MessageId`. If a later namespace uses more
partitions, uniqueness is `MessageId + PartitionKey`. Nexus supplies no tenant
partition key and makes no ordering guarantee. With duplicate detection enabled
and neither `SessionId` nor `PartitionKey` supplied, Service Bus can use
`MessageId` for partition selection.

## Retry and dead-letter boundaries

Event Grid retries for at most 30 attempts or 1,440 minutes, whichever limit is
reached first. Failed Event Grid delivery is written to the private
`event-grid-deadletter` container.

The File subscription's subject filter names only the canonical File container
and `files/` prefix. A Blob created in `event-grid-deadletter` must never match
the File subscription. This feedback-loop exclusion is a hard deployment
invariant.

Event Grid dead-letter storage and the Service Bus DLQ represent different
failures:

- Event Grid dead letter: Event Grid could not deliver to Service Bus.
- Service Bus DLQ: Service Bus accepted the message but the future worker could
  not process it.

Service Bus DLQ messages do not observe TTL and do not expire automatically.
Before the Phase 13 worker is activated, operations must define inspection,
safe replay, explicit purge procedures, and DLQ-size alerting. A valid message
that exhausted delivery during a prolonged dependency outage may be replayed
only after recovery is verified, preserving its original event body and
correlation identity. Phase 14 business idempotency must make that redelivery
safe. Permanently invalid messages remain quarantined and must not be replayed
unchanged. Do not let an unbounded DLQ become silent operational storage.

Retain Event Grid dead-letter objects for 30 days after the originating failure
is resolved, unless the incident/audit policy requires longer. An account-wide
Storage lifecycle policy is outside Phase 12 because overwriting one could
affect unrelated containers. Until safe container-scoped automation exists,
retention and removal are an explicit operations responsibility and production
deployment prerequisite.

Phase 13 must dead-letter every Phase 11
`AzureBlobCreatedEventMappingError` immediately using the bounded safe reason
`INVALID_BLOB_CREATED_EVENT`. The normal expected baseline is zero. Every
occurrence must produce a structured log or metric with safe correlation and
be sent immediately to the DLQ. Monitoring must raise one grouped
operational/security alert when the count is at least one during a short
monitoring window. Additional occurrences in that window increment logs and
metrics without producing one page per message. Do not copy raw event payloads,
SAS data, protected UploadContext ciphertext, secrets, or provider details into
the reason. Temporary Azure Storage, PostgreSQL, Key Vault, and network
failures may follow retry/abandon semantics.

The Phase 13 consumer accepts only AMQP DATA byte sections containing a JSON
object, with a Nexus aggregate body limit of 64 KiB (65,536 bytes). This is
smaller than and independent of the queue limit. Unsupported body forms,
invalid UTF-8/JSON, and oversized bodies are immediately dead-lettered with
`INVALID_MESSAGE_BODY`.

Unexpected handler failures are explicitly abandoned. Before receiving again,
the worker uses a process-local jittered exponential delay whose nominal values
start at two seconds and double to a 60-second cap; each actual delay remains
between one-half and all of its nominal value. Successful handling resets the
delay. Graceful shutdown stops new receives and gives an in-flight handler up
to ten seconds to finish. Success is completed; failure is abandoned; and a
handler that exceeds the bound is cancelled before an abandon attempt. No
failure cooldown is applied during shutdown.

Recoverable Service Bus connection failures recreate the receiver after a
bounded delay. Authentication, authorization, missing-entity, and
disabled-entity failures terminate the worker after a safe error-type-only log;
they are not treated as reconnectable outages.

## Orphan reconciliation and release gate

Nexus uses one canonical File container. It does not move successful uploads
between incoming and permanent containers and does not use worker-written
lifecycle markers as the sole orphan detector.

Before unrestricted public upload traffic is enabled, Nexus must have an
approved reconciliation design and operational schedule for sufficiently old
committed objects that lack legitimate File state. The release gate must also
include PENDING-age monitoring and alerting because a File can remain PENDING
indefinitely when the Defender scan cap is exhausted, Defender is disabled, or
its scan-result delivery is dead-lettered. Reconciliation must classify
each candidate for recovery, quarantine, or deletion. At large scale, use an
inventory or change-driven mechanism rather than frequent full-container scans.

Abandoned browser block uploads can leave uncommitted blocks. Azure garbage
collects uncommitted blocks after approximately seven days without another
successful block operation. Those staged bytes consume storage during that
retention period and upload/storage operations can incur charges. Phase 12 does
not add a custom uncommitted-block cleanup process; capacity and cost reviews
must account for the retention window.

## Defender for Storage malware results

Phase 15 enables Microsoft Defender for Storage on-upload malware scanning for
the configured storage account. `defenderForStorageSettings/current` is an
account-wide resource, and this template uses
`overrideSubscriptionLevelSettings: true`. The Nexus File storage account
should therefore be dedicated to the File capability so this deployment does
not unexpectedly override Defender settings for unrelated storage workloads.
The existing storage-account Event Grid system topic must be in the same
resource group as the storage account so Defender can use the single system
topic allowed for that source and send every scan result to the dedicated
`malwareScanTopicName` Event Grid custom topic. That topic uses its
system-assigned Managed Identity to deliver into the dedicated
`file-malware-scan-results` Service Bus queue. The same identity receives
narrow write access to the Event Grid dead-letter container. Defender provisioning is also expected to grant its
scanner/service identity the permissions needed to publish scan results to the
custom topic; controlled deployment must verify the resulting Event Grid Data
Sender assignment before traffic is enabled.

Nexus configures `blobScanResultsOptions: None`. File security state therefore
does not depend on Blob index tags, and Defender result-tag writes cannot alter
the Phase 14 ETag comparison. The malware-result custom topic also sets
`disableLocalAuth: true`; Defender publishing must succeed through Microsoft
Entra/RBAC only. Controlled validation must prove the Defender publisher can
still emit scan results with local authentication disabled and that no topic
access key is required or accepted for Nexus operation. The worker must receive
`AZURE_MALWARE_SCAN_EXPECTED_TOPIC` equal to the deployed
`malwareScanTopicResourceId` output.

`malwareScanCapGBPerMonth` is explicit. Choose it from expected workload and
cost controls; `-1` means unlimited. Reaching the configured scanning cap or
receiving another unsuccessful scan result must never make a File available.
The application maps a clean result to `AVAILABLE` and malicious, error, or
not-scanned results to `FAILED`.

Defender results and BlobCreated events are unordered. They use separate queues
so an early scan result cannot repeatedly redeliver ahead of and starve the
BlobCreated registration message. Scan results for uploads that Phase 14
permanently rejected have no File row to update; those malware messages will
retry and can eventually dead-letter. That is expected DLQ noise and should be
distinguished from unexpected processing failures. If a valid scan result
still arrives before Phase 14 has registered the File row, its consumer abandons
it for retry. Redelivery of the same terminal result is idempotent. A
contradictory terminal result is dead-lettered as
`INVALID_MALWARE_SCAN_RESULT`.

## Controlled Azure validation

Ordinary CI compiles Bicep without Azure credentials. It does not prove Azure
Managed Identity, RBAC, firewall, Event Grid, or Premium Service Bus behavior.

Run live validation in a scheduled, short-lived Premium environment. Record its
start/end time, selected region, live cost estimate, operators, and cleanup
owner. Delete the Premium namespace and validation-only resources immediately
after evidence is captured.

The validation run must prove:

1. Defender can publish malware scan results to the custom Event Grid topic
   with `disableLocalAuth: true`, using the expected RBAC-authorized identity,
   and Nexus requires no topic access key.
2. `PutBlob` and `PutBlockList` produce CloudEvents 1.0 messages.
3. BlobDeleted, another container, and another key namespace do not route.
4. The exact emitted Event Grid source is captured for Phase 11 configuration.
5. Event Grid Managed Identity can send and unauthorized identities cannot.
6. With storage account A configured, selecting a system topic whose source is
   storage account B fails closed before creating either the queue sender or
   dead-letter Blob role assignment. Retain deployment and role-assignment
   evidence for this negative case.
7. `aeg-output-event-id` is present.
8. Reproduced Event Grid redelivery retains the same Service Bus `MessageId`.
9. Forced Event Grid delivery failure creates a dead-letter object.
10. That dead-letter Blob does not create another File completion message.
11. Queue, DLQ, Event Grid failure, CPU, memory, and throttling metrics are
    visible.
12. First deployment behavior is recorded, including any transient Event Grid
    authorization failure, RBAC propagation wait, and successful idempotent
    redeployment.

The production firewall posture must not be relaxed permanently for
validation. If an operator needs queue read access, add both narrow temporary
RBAC and a temporary IP/network rule for the validation source. Record the rule
identifier and removal evidence in the runbook. Remove both immediately after
validation; keep local authentication disabled throughout.

Before production worker activation, use the pinned Python `azure-servicebus`
SDK during this controlled run to capture a real BlobCreated delivery's
`ServiceBusReceivedMessage.body_type`, DATA-section shape, and encoded size.
Verify that it is `AmqpMessageBodyType.DATA`, contains byte sections, and is
accepted by the Nexus 64-KiB DATA-only decoder. If the real delivery differs,
review the contract instead of silently loosening the decoder.

## Deployment outline

Compile without credentials:

```bash
make infra-check
```

For new-system-topic mode, deploy the shared topic explicitly at its resource
group scope and retain its output resource ID. For either mode, deploy the File
pipeline at subscription scope with an intentionally reviewed parameter file:

```bash
az deployment sub create \
  --location <deployment-record-region> \
  --template-file infra/azure/file-upload-events.bicep \
  --parameters infra/azure/file-upload-events.example.bicepparam
```

The CLI `--location` above stores the subscription-scope deployment record. It
does not select the Service Bus resource region; the template derives that
region directly from the configured Nexus storage account.

The example file is illustrative and contains no credentials. Replace every
placeholder and review the immutable partition count before deployment.

The API and File worker must receive the same
`FILE_UPLOAD_MAX_SIZE_BYTES` value. A mismatch can authorize a valid browser
upload at the API and then permanently reject it in the worker. Each worker
process handles one message at a time and starts with a two-connection database
pool and zero overflow; capacity review must multiply those settings by the
maximum worker replica count.

If `FILE_UPLOAD_CONTEXT_KEY` is misconfigured, otherwise valid uploads are
dead-lettered with `INVALID_UPLOAD_COMPLETION`. Recovery is to restore the
correct protected-context key, verify worker health, and safely replay the
affected DLQ messages. Do not copy protected context values into runbook notes
or logs.

Phase 14 deliberately does not delete rejected Blobs. They remain in the File
container and accumulate until reconciliation classifies them for recovery,
quarantine, or deletion.

Phase 15 disables Defender Blob index-tag result writes. Controlled validation
must instead prove safe and EICAR-style test uploads produce the expected
malware result event, preserve the scanned Blob ETag, reach the File queue, and
drive the expected AVAILABLE or FAILED transition.

## Operational metrics and gates

Production monitoring must cover:

- Event Grid delivery failures and dead-letter writes;
- Service Bus incoming, active, and dead-letter message counts;
- queue depth and processing lag;
- throttled requests and server errors;
- namespace CPU and memory;
- assigned Messaging Units.

Capacity changes follow measurements, not user count. Alerts and reconciliation
are release requirements even when the monitoring platform itself is delivered
by a later shared observability phase.

### Document processing (DP-04)

Deploy `document-processing.bicep` into the resource group containing the existing
Nexus Service Bus namespace; it creates only `document-processing-requests` and
optional queue-scoped RBAC assignments. Supply the dispatcher's Managed Identity
principal for Data Sender. Leave the consumer principal/deployment unactivated
until a real downstream processor is integrated. The template neither changes
namespace network rules nor enables shared-key authentication. Provide the same
private/approved network reachability as the existing File workers.

Production dispatcher: `python -m nexus.workers.document_processing`, requiring
`DATABASE_URL` and `AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE`.
Optional `AZURE_SERVICE_BUS_MANAGED_IDENTITY_CLIENT_ID` selects an identity.
`AZURE_SERVICE_BUS_DOCUMENT_QUEUE_NAME` defaults to `document-processing-requests`.
Defaults: `DOCUMENT_DATABASE_POOL_SIZE=2` (zero overflow),
`DOCUMENT_DISPATCH_CONCURRENCY=2`, `DOCUMENT_DISPATCH_LEASE_SECONDS=60`,
`DOCUMENT_DISPATCH_SEND_TIMEOUT_SECONDS=20`, `DOCUMENT_DISPATCH_POLL_SECONDS=2`.
Future consumption defaults: `DOCUMENT_WORKER_CONCURRENCY=2`,
`DOCUMENT_WORKER_MAX_LOCK_RENEWAL_SECONDS=300`, `DOCUMENT_PROCESSING_VERSION=dp-04`.
Send timeout must be shorter than the lease. Receive prefetch is always zero.

For local use, run `docker compose --profile azure-emulators up document-dispatcher`
after migrating the database. Connection-string authentication lives only in
`nexus.dev.local_document_dispatcher`, restricted to development/test. The shared
emulator has the dedicated queue; no local fake processor/consumer is deployed.

Monitor pending-request age, dispatch failure counts, queue depth, DLQ depth, and
stalled PROCESSING Documents. The queue retains deliveries for seven days and
DLQs expiry/max-delivery failures. Delivery is at least once; duplicate detection
is optional traffic reduction. DB acknowledgement does not prove Document completion.
DP-04 provides transport resend only, not DLQ replay or interrupted-processing
recovery (DP-11). Before enabling dispatch in production, ensure queue capacity
and retention cover the period until real consumers are activated.
