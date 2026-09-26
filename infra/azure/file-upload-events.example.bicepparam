using './file-upload-events.bicep'

param serviceBusResourceGroupName = 'nexus-production-messaging'
param serviceBusNamespaceName = 'replace-with-globally-unique-namespace'
param queueName = 'file-upload-completions'

// Immutable launch choice: one Premium partition with one total Messaging Unit.
param premiumMessagingPartitions = 1
param messagingUnits = 1

param storageResourceGroupName = 'nexus-production-storage'
param storageAccountName = 'replacewithstorageaccount'
param fileContainerName = 'nexus-files'
param deadLetterContainerName = 'event-grid-deadletter'

// Existing-topic mode is always explicit. For new-topic mode, first deploy
// shared-storage-system-topic.bicep, then supply its output resource ID here.
param systemTopicResourceGroupName = 'nexus-production-storage'
param systemTopicName = 'nexus-storage-events'
param systemTopicResourceId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/nexus-production-storage/providers/Microsoft.EventGrid/systemTopics/nexus-storage-events'
param eventSubscriptionName = 'nexus-file-upload-completions'

param malwareScanTopicName = 'nexus-file-malware-scan-results'
param malwareScanEventSubscriptionName = 'nexus-file-malware-scan-results'
// Explicit cost/safety limit for the example deployment. Review per environment.
param malwareScanCapGBPerMonth = 500

// The routing template does not deploy a worker identity. When the worker is activated,
// pass its user-assigned Managed Identity principal ID to create queue-scoped
// Azure Service Bus Data Receiver access.
param fileWorkerPrincipalId = ''
