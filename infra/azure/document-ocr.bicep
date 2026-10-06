targetScope = 'resourceGroup'

metadata description = 'Grant the Document worker analyze access to a pre-provisioned Document Intelligence resource.'

@description('Existing single-service Document Intelligence account with a custom subdomain and local authentication disabled.')
param documentIntelligenceAccountName string

@description('Object ID of the Document worker Managed Identity, not its client ID.')
param workerPrincipalId string

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: documentIntelligenceAccountName
}

var analysisRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')

resource analysisAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, workerPrincipalId, analysisRole)
  scope: account
  properties: {
    principalId: workerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: analysisRole
  }
}

output documentIntelligenceEndpoint string = account.properties.endpoint
