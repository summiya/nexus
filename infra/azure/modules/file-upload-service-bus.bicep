metadata description = 'Creates the Premium Service Bus namespace and shared Nexus File completion queue.'

@description('Azure region for the namespace.')
param location string

@description('Globally unique Service Bus namespace name.')
param namespaceName string

@description('File upload-completion queue name.')
param queueName string

@description('Defender malware scan-result queue name.')
param malwareScanQueueName string

@allowed([
  1
  2
  4
])
param premiumMessagingPartitions int

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

@minValue(1)
param queueMaxSizeInMegabytes int
param duplicateDetectionHistoryTimeWindow string

@description('System-assigned principal ID of the explicitly selected Event Grid system topic.')
param eventGridPrincipalId string

@description('System-assigned principal ID of the Defender malware scan result Event Grid topic.')
param malwareScanTopicPrincipalId string

@description('Optional user-assigned File worker principal. Empty creates no receiver role assignment.')
param fileWorkerPrincipalId string = ''

var serviceBusDataSenderRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
)

var serviceBusDataReceiverRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
)

var messagingUnitsAreMultiple = messagingUnits % premiumMessagingPartitions == 0
var messagingUnitsFitPartitions = messagingUnits <= premiumMessagingPartitions * 16
var messagingUnitsAreCompatible = messagingUnitsAreMultiple && messagingUnitsFitPartitions
var validatedMessagingUnits = messagingUnitsAreCompatible
  ? messagingUnits
  : fail('Messaging Units are incompatible with the Premium partition count.')

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2026-01-01' = {
  name: namespaceName
  location: location
  sku: {
    name: 'Premium'
    tier: 'Premium'
    capacity: validatedMessagingUnits
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    premiumMessagingPartitions: premiumMessagingPartitions
    publicNetworkAccess: 'Enabled'
  }
}

resource networkRules 'Microsoft.ServiceBus/namespaces/networkRuleSets@2026-01-01' = {
  name: 'default'
  parent: serviceBusNamespace
  properties: {
    defaultAction: 'Deny'
    ipRules: []
    publicNetworkAccess: 'Enabled'
    trustedServiceAccessEnabled: true
    virtualNetworkRules: []
  }
}

resource queue 'Microsoft.ServiceBus/namespaces/queues@2026-01-01' = {
  name: queueName
  parent: serviceBusNamespace
  properties: {
    autoDeleteOnIdle: 'P10675199DT2H48M5.4775807S'
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P7D'
    duplicateDetectionHistoryTimeWindow: duplicateDetectionHistoryTimeWindow
    enableBatchedOperations: true
    enableExpress: false
    lockDuration: 'PT1M'
    maxDeliveryCount: 10
    maxMessageSizeInKilobytes: 1024
    maxSizeInMegabytes: queueMaxSizeInMegabytes
    requiresDuplicateDetection: true
    requiresSession: false
    status: 'Active'
  }
  dependsOn: [
    networkRules
  ]
}

resource malwareScanQueue 'Microsoft.ServiceBus/namespaces/queues@2026-01-01' = {
  name: malwareScanQueueName
  parent: serviceBusNamespace
  properties: {
    autoDeleteOnIdle: 'P10675199DT2H48M5.4775807S'
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P7D'
    duplicateDetectionHistoryTimeWindow: duplicateDetectionHistoryTimeWindow
    enableBatchedOperations: true
    enableExpress: false
    lockDuration: 'PT1M'
    maxDeliveryCount: 10
    maxMessageSizeInKilobytes: 1024
    maxSizeInMegabytes: queueMaxSizeInMegabytes
    requiresDuplicateDetection: true
    requiresSession: false
    status: 'Active'
  }
  dependsOn: [
    networkRules
  ]
}

resource eventGridSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(queue.id, eventGridPrincipalId, serviceBusDataSenderRoleDefinitionId)
  scope: queue
  properties: {
    principalId: eventGridPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: serviceBusDataSenderRoleDefinitionId
  }
}

resource malwareScanTopicSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(malwareScanQueue.id, malwareScanTopicPrincipalId, serviceBusDataSenderRoleDefinitionId)
  scope: malwareScanQueue
  properties: {
    principalId: malwareScanTopicPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: serviceBusDataSenderRoleDefinitionId
  }
}

resource fileWorkerReceiverRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(trim(fileWorkerPrincipalId))) {
  name: guid(queue.id, fileWorkerPrincipalId, serviceBusDataReceiverRoleDefinitionId)
  scope: queue
  properties: {
    principalId: fileWorkerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: serviceBusDataReceiverRoleDefinitionId
  }
}

resource fileWorkerMalwareScanReceiverRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(trim(fileWorkerPrincipalId))) {
  name: guid(malwareScanQueue.id, fileWorkerPrincipalId, serviceBusDataReceiverRoleDefinitionId)
  scope: malwareScanQueue
  properties: {
    principalId: fileWorkerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: serviceBusDataReceiverRoleDefinitionId
  }
}

output namespaceResourceId string = serviceBusNamespace.id
output queueResourceId string = queue.id
output malwareScanQueueResourceId string = malwareScanQueue.id
