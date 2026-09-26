metadata description = 'Creates the private Event Grid dead-letter container and its narrow writer assignment.'

param storageAccountName string
param containerName string

@description('System-assigned principal ID of the explicitly selected Event Grid system topic.')
param eventGridPrincipalId string

@description('System-assigned principal ID of the Defender malware scan result Event Grid topic.')
param malwareScanTopicPrincipalId string

var storageBlobDataContributorRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

resource storageAccount 'Microsoft.Storage/storageAccounts@2026-04-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2026-04-01' existing = {
  name: 'default'
  parent: storageAccount
}

resource deadLetterContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-04-01' = {
  name: containerName
  parent: blobService
  properties: {
    publicAccess: 'None'
  }
}

resource eventGridDeadLetterRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(deadLetterContainer.id, eventGridPrincipalId, storageBlobDataContributorRoleDefinitionId)
  scope: deadLetterContainer
  properties: {
    principalId: eventGridPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRoleDefinitionId
  }
}

resource malwareScanDeadLetterRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(deadLetterContainer.id, malwareScanTopicPrincipalId, storageBlobDataContributorRoleDefinitionId)
  scope: deadLetterContainer
  properties: {
    principalId: malwareScanTopicPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRoleDefinitionId
  }
}

output containerResourceId string = deadLetterContainer.id
output storageAccountId string = storageAccount.id
