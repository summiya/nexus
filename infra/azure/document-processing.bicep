targetScope = 'resourceGroup'

metadata description = 'Dedicated Document request queue on the existing Nexus Service Bus namespace.'

param serviceBusNamespaceName string
param queueName string = 'document-processing-requests'
param dispatcherPrincipalId string = ''
param workerPrincipalId string = ''
@minValue(1)
@maxValue(100)
param maxDeliveryCount int = 10
param storageAccountName string = ''
param fileContainerName string = ''
param storagePrincipalId string = workerPrincipalId

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
    maxDeliveryCount: maxDeliveryCount
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

// Optional container-scoped read/create access for verified sources and immutable artifacts.
resource storageAccount 'Microsoft.Storage/storageAccounts@2026-04-01' existing = {
  name: storageAccountName
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2026-04-01' existing = {
  parent: storageAccount
  name: 'default'
}
resource fileContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-04-01' existing = {
  parent: blobService
  name: fileContainerName
}
var blobContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
resource documentStorageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(storageAccountName) && !empty(fileContainerName) && !empty(storagePrincipalId)) {
  name: guid(fileContainer.id, storagePrincipalId, blobContributorRole)
  scope: fileContainer
  properties: {
    principalId: storagePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributorRole
  }
}
