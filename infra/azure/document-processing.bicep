targetScope = 'resourceGroup'

metadata description = 'Dedicated Document request queue on the existing Nexus Service Bus namespace.'

param serviceBusNamespaceName string
param queueName string = 'document-processing-requests'
param dispatcherPrincipalId string = ''
param workerPrincipalId string = ''

resource namespace 'Microsoft.ServiceBus/namespaces@2026-01-01' existing = {
  name: serviceBusNamespaceName
}

resource queue 'Microsoft.ServiceBus/namespaces/queues@2026-01-01' = {
  parent: namespace
  name: queueName
  properties: {
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P7D'
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    enableBatchedOperations: true
    enableExpress: false
    lockDuration: 'PT1M'
    maxDeliveryCount: 10
    maxSizeInMegabytes: 1024
    requiresDuplicateDetection: true
    requiresSession: false
    status: 'Active'
  }
}

var senderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39')
var receiverRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0')

resource sender 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(trim(dispatcherPrincipalId))) {
  name: guid(queue.id, dispatcherPrincipalId, senderRole)
  scope: queue
  properties: {
    principalId: dispatcherPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: senderRole
  }
}

resource receiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(trim(workerPrincipalId))) {
  name: guid(queue.id, workerPrincipalId, receiverRole)
  scope: queue
  properties: {
    principalId: workerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: receiverRole
  }
}

output queueResourceId string = queue.id
