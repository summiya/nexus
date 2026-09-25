metadata description = 'Creates the Premium Service Bus namespace and shared Nexus File completion queue.'

@description('Azure region for the namespace.')
param location string

@description('Globally unique Service Bus namespace name.')
param namespaceName string

@description('Shared File upload-completion queue name.')
param queueName string

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

var serviceBusDataSenderRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
)

var messagingUnitsAreMultiple = messagingUnits % premiumMessagingPartitions == 0
var messagingUnitsFitPartitions = messagingUnits <= premiumMessagingPartitions * 16
var messagingUnitsAreCompatible = messagingUnitsAreMultiple && messagingUnitsFitPartitions
var validatedMessagingUnits = messagingUnitsAreCompatible
  ? messagingUnits
  : fail('Messaging Units are incompatible with the Premium partition count.')

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
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

resource networkRules 'Microsoft.ServiceBus/namespaces/networkRuleSets@2024-01-01' = {
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

resource queue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
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

resource eventGridSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(queue.id, eventGridPrincipalId, serviceBusDataSenderRoleDefinitionId)
  scope: queue
  properties: {
    principalId: eventGridPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: serviceBusDataSenderRoleDefinitionId
  }
}

output namespaceResourceId string = serviceBusNamespace.id
output queueResourceId string = queue.id
