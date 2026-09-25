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
