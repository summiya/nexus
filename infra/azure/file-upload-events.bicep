targetScope = 'subscription'

metadata description = 'Routes File upload and Defender malware-scan events into the durable Nexus File queue.'

@description('Resource group that will own the Service Bus namespace.')
param serviceBusResourceGroupName string

@description('Globally unique Service Bus Premium namespace name.')
param serviceBusNamespaceName string

@description('Queue for committed Nexus File upload events.')
param queueName string = 'file-upload-completions'

@description('Queue for Defender malware scan result events.')
param malwareScanQueueName string = 'file-malware-scan-results'

@description('Immutable Premium namespace partition count. Nexus launches with one partition.')
@allowed([
  1
  2
  4
])
param premiumMessagingPartitions int

@description('Total Premium Messaging Units. Must be a multiple of premiumMessagingPartitions.')
@allowed([
  1
  2
  4
  8
  16
  32
  64
])
param messagingUnits int

@description('Resource group containing the existing Nexus Blob Storage account.')
param storageResourceGroupName string

@description('Subscription containing the existing Nexus Blob Storage account.')
param storageSubscriptionId string = subscription().subscriptionId

@description('Existing Nexus Blob Storage account name.')
param storageAccountName string

@description('Existing canonical File blob container name.')
param fileContainerName string

@description('Dedicated Event Grid delivery-failure container.')
param deadLetterContainerName string = 'event-grid-deadletter'

@description('Full resource ID of the explicitly selected existing Event Grid system topic.')
param systemTopicResourceId string

@description('Subscription containing the explicitly selected system topic.')
param systemTopicSubscriptionId string = subscription().subscriptionId

@description('Resource group containing the explicitly selected system topic.')
param systemTopicResourceGroupName string

@description('Name of the explicitly selected existing Event Grid system topic.')
param systemTopicName string

@description('Nexus-owned File event-subscription name on the shared system topic.')
param eventSubscriptionName string = 'nexus-file-upload-completions'

@description('Dedicated custom Event Grid topic for Defender malware scan results.')
param malwareScanTopicName string = 'nexus-file-malware-scan-results'

@description('Nexus-owned Defender result event-subscription name.')
param malwareScanEventSubscriptionName string = 'nexus-file-malware-scan-results'

@description('Maximum Defender on-upload malware scanning volume per month in GB. Use -1 for unlimited.')
param malwareScanCapGBPerMonth int

@description('Service Bus duplicate-detection history window.')
param duplicateDetectionHistoryTimeWindow string = 'PT10M'

@description('Maximum queue capacity in MiB. The Phase 12 baseline is 80 GiB.')
param queueMaxSizeInMegabytes int = 81920

@description('Optional user-assigned Managed Identity principal for the File worker. Empty creates no worker role assignments.')
param fileWorkerPrincipalId string = ''

var expectedSystemTopicResourceId = resourceId(
  systemTopicSubscriptionId,
  systemTopicResourceGroupName,
  'Microsoft.EventGrid/systemTopics',
  systemTopicName
)
var validatedSystemTopicName = toLower(systemTopicResourceId) == toLower(expectedSystemTopicResourceId)
  ? systemTopicName
  : fail('The explicit Event Grid system-topic resource ID is inconsistent.')

resource storageAccount 'Microsoft.Storage/storageAccounts@2026-04-01' existing = {
  name: storageAccountName
  scope: resourceGroup(storageSubscriptionId, storageResourceGroupName)
}

resource systemTopic 'Microsoft.EventGrid/systemTopics@2025-02-15' existing = {
  name: validatedSystemTopicName
  scope: resourceGroup(systemTopicSubscriptionId, systemTopicResourceGroupName)
}

var systemTopicHasTrustedSource = toLower(systemTopic.properties.source) == toLower(storageAccount.id)
var systemTopicHasTrustedType = systemTopic.properties.topicType == 'Microsoft.Storage.StorageAccounts'
var trustedSystemTopicName = systemTopicHasTrustedSource
  ? systemTopicHasTrustedType
    ? validatedSystemTopicName
    : fail('The Event Grid system-topic type is invalid.')
  : fail('The Event Grid system-topic source is invalid.')
var systemTopicHasSystemAssignedIdentity = contains(systemTopic.identity.?type ?? '', 'SystemAssigned')
var systemTopicPrincipalId = systemTopic.identity.?principalId ?? ''
var trustedEventGridPrincipalId = trustedSystemTopicName == validatedSystemTopicName && systemTopicHasSystemAssignedIdentity && !empty(trim(systemTopicPrincipalId))
  ? systemTopicPrincipalId
  : fail('The Event Grid system-topic identity is invalid.')

module malwareScanTopic './modules/file-malware-scan-topic.bicep' = {
  name: 'nexus-file-malware-scan-topic'
  scope: resourceGroup(storageSubscriptionId, storageResourceGroupName)
  params: {
    deadLetterContainerName: deadLetterContainerName
    location: storageAccount.location
    malwareScanCapGBPerMonth: malwareScanCapGBPerMonth
    malwareScanTopicName: malwareScanTopicName
    storageAccountName: storageAccountName
  }
}

module serviceBus './modules/file-upload-service-bus.bicep' = {
  name: 'nexus-file-upload-service-bus'
  scope: resourceGroup(serviceBusResourceGroupName)
  params: {
    eventGridPrincipalId: trustedEventGridPrincipalId
    malwareScanTopicPrincipalId: malwareScanTopic.outputs.topicPrincipalId
    fileWorkerPrincipalId: fileWorkerPrincipalId
    location: storageAccount.location
    malwareScanQueueName: malwareScanQueueName
    messagingUnits: messagingUnits
    namespaceName: serviceBusNamespaceName
    premiumMessagingPartitions: premiumMessagingPartitions
    queueMaxSizeInMegabytes: queueMaxSizeInMegabytes
    queueName: queueName
    duplicateDetectionHistoryTimeWindow: duplicateDetectionHistoryTimeWindow
  }
}

module deadLetterStorage './modules/file-upload-dead-letter-storage.bicep' = {
  name: 'nexus-file-upload-event-grid-dead-letter'
  scope: resourceGroup(storageSubscriptionId, storageResourceGroupName)
  params: {
    containerName: deadLetterContainerName
    eventGridPrincipalId: trustedEventGridPrincipalId
    malwareScanTopicPrincipalId: malwareScanTopic.outputs.topicPrincipalId
    storageAccountName: storageAccountName
  }
}

module fileWorkerStorageAccess './modules/file-worker-storage-access.bicep' = if (!empty(trim(fileWorkerPrincipalId))) {
  name: 'nexus-file-upload-worker-storage-access'
  scope: resourceGroup(storageSubscriptionId, storageResourceGroupName)
  params: {
    fileContainerName: fileContainerName
    fileWorkerPrincipalId: fileWorkerPrincipalId
    storageAccountName: storageAccountName
  }
}

module eventSubscription './modules/file-upload-event-subscription.bicep' = {
  name: 'nexus-file-upload-event-subscription'
  scope: resourceGroup(systemTopicSubscriptionId, systemTopicResourceGroupName)
  params: {
    deadLetterContainerName: deadLetterContainerName
    deadLetterStorageAccountId: deadLetterStorage.outputs.storageAccountId
    eventSubscriptionName: eventSubscriptionName
    fileContainerName: fileContainerName
    queueResourceId: serviceBus.outputs.queueResourceId
    systemTopicName: trustedSystemTopicName
  }
}

module malwareScanSubscription './modules/file-malware-scan-subscription.bicep' = {
  name: 'nexus-file-malware-scan-subscription'
  scope: resourceGroup(storageSubscriptionId, storageResourceGroupName)
  params: {
    deadLetterContainerName: deadLetterContainerName
    deadLetterStorageAccountId: deadLetterStorage.outputs.storageAccountId
    eventSubscriptionName: malwareScanEventSubscriptionName
    malwareScanTopicName: malwareScanTopic.outputs.topicName
    queueResourceId: serviceBus.outputs.malwareScanQueueResourceId
  }
}

output eventSubscriptionResourceId string = eventSubscription.outputs.eventSubscriptionResourceId
output malwareScanEventSubscriptionResourceId string = malwareScanSubscription.outputs.eventSubscriptionResourceId
output malwareScanTopicResourceId string = malwareScanTopic.outputs.topicResourceId
output fileUploadQueueResourceId string = serviceBus.outputs.queueResourceId
output malwareScanQueueResourceId string = serviceBus.outputs.malwareScanQueueResourceId
output eventGridDeadLetterContainerResourceId string = deadLetterStorage.outputs.containerResourceId
output premiumPartitionCount int = premiumMessagingPartitions
output messagingUnitCapacity int = messagingUnits
