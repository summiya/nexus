# Nexus File Upload Event Routing

This directory contains the EPIC 05 Phase 12 Azure infrastructure for routing
committed Nexus File blobs into a durable queue. It intentionally stops before
the Service Bus worker:

```text
File Blob container
    -> Event Grid system topic
    -> Nexus File event subscription
    -> Service Bus queue
    -> STOP (Phase 13)
```

No template in this directory creates a worker, database receipt table, Redis
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

Duplicate detection is load reduction only. Phase 13 correctness must still
enforce `(source, event_id)`, complete File business identity, immutable
ownership, and database invariants.

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
Before Phase 13 is released, operations must define inspection, safe replay,
and explicit purge procedures and alert on DLQ size. Do not let an unbounded DLQ
become silent operational storage.

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

## Orphan reconciliation and release gate

Nexus uses one canonical File container. It does not move successful uploads
between incoming and permanent containers and does not use worker-written
lifecycle markers as the sole orphan detector.

Before unrestricted public upload traffic is enabled, Nexus must have an
approved reconciliation design and operational schedule for sufficiently old
committed objects that lack legitimate File state. Reconciliation must classify
each candidate for recovery, quarantine, or deletion. At large scale, use an
inventory or change-driven mechanism rather than frequent full-container scans.

Abandoned browser block uploads can leave uncommitted blocks. Azure garbage
collects uncommitted blocks after approximately seven days without another
successful block operation. Those staged bytes consume storage during that
retention period and upload/storage operations can incur charges. Phase 12 does
not add a custom uncommitted-block cleanup process; capacity and cost reviews
must account for the retention window.

## Controlled Azure validation

Ordinary CI compiles Bicep without Azure credentials. It does not prove Azure
Managed Identity, RBAC, firewall, Event Grid, or Premium Service Bus behavior.

Run live validation in a scheduled, short-lived Premium environment. Record its
start/end time, selected region, live cost estimate, operators, and cleanup
owner. Delete the Premium namespace and validation-only resources immediately
after evidence is captured.

The validation run must prove:

1. `PutBlob` and `PutBlockList` produce CloudEvents 1.0 messages.
2. BlobDeleted, another container, and another key namespace do not route.
3. The exact emitted Event Grid source is captured for Phase 11 configuration.
4. Event Grid Managed Identity can send and unauthorized identities cannot.
5. With storage account A configured, selecting a system topic whose source is
   storage account B fails closed before creating either the queue sender or
   dead-letter Blob role assignment. Retain deployment and role-assignment
   evidence for this negative case.
6. `aeg-output-event-id` is present.
7. Reproduced Event Grid redelivery retains the same Service Bus `MessageId`.
8. Forced Event Grid delivery failure creates a dead-letter object.
9. That dead-letter Blob does not create another File completion message.
10. Queue, DLQ, Event Grid failure, CPU, memory, and throttling metrics are
   visible.
11. First deployment behavior is recorded, including any transient Event Grid
    authorization failure, RBAC propagation wait, and successful idempotent
    redeployment.

The production firewall posture must not be relaxed permanently for
validation. If an operator needs queue read access, add both narrow temporary
RBAC and a temporary IP/network rule for the validation source. Record the rule
identifier and removal evidence in the runbook. Remove both immediately after
validation; keep local authentication disabled throughout.

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
