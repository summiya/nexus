metadata description = 'Creates the dedicated provider-credential Key Vault and grants the API identity secret lifecycle access.'

@description('Azure region for the provider-credential Key Vault.')
param location string

@minLength(3)
@maxLength(24)
@description('Globally unique provider-credential Key Vault name.')
param keyVaultName string

@description('Existing Nexus API Managed Identity principal ID.')
param apiManagedIdentityPrincipalId string

resource providerCredentialVault 'Microsoft.KeyVault/vaults@2026-02-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Enabled'
  }
}

var keyVaultSecretsOfficerRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
)

resource apiSecretsOfficerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(providerCredentialVault.id, apiManagedIdentityPrincipalId, keyVaultSecretsOfficerRoleDefinitionId)
  scope: providerCredentialVault
  properties: {
    principalId: apiManagedIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsOfficerRoleDefinitionId
  }
}

output vaultUri string = providerCredentialVault.properties.vaultUri
output vaultResourceId string = providerCredentialVault.id
