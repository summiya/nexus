metadata description = 'Grants the File worker read-only Blob data access to the canonical File container.'

@description('Existing Nexus Blob Storage account name.')
param storageAccountName string

@description('Existing canonical File container name.')
param fileContainerName string

@description('User-assigned Managed Identity principal for the File worker.')
param fileWorkerPrincipalId string

resource storageAccount 'Microsoft.Storage/storageAccounts@2026-04-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2026-04-01' existing = {
  name: 'default'
  parent: storageAccount
}

resource fileContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-04-01' existing = {
  name: fileContainerName
  parent: blobService
}

var storageBlobDataReaderRoleDefinitionId = tenantResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
)

resource fileWorkerBlobReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(fileContainer.id, fileWorkerPrincipalId, storageBlobDataReaderRoleDefinitionId)
  scope: fileContainer
  properties: {
    principalId: fileWorkerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataReaderRoleDefinitionId
  }
}
