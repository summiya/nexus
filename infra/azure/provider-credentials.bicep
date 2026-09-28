targetScope = 'resourceGroup'

metadata description = 'Deploys dedicated Azure Key Vault storage for Nexus model-provider credentials.'

@description('Azure region for the provider-credential Key Vault.')
param location string = resourceGroup().location

@description('Globally unique provider-credential Key Vault name.')
param keyVaultName string

@description('Existing Nexus API Managed Identity principal ID.')
param apiManagedIdentityPrincipalId string

module providerCredentialKeyVault './modules/provider-credential-key-vault.bicep' = {
  name: 'provider-credential-key-vault'
  params: {
    location: location
    keyVaultName: keyVaultName
    apiManagedIdentityPrincipalId: apiManagedIdentityPrincipalId
  }
}

output vaultUri string = providerCredentialKeyVault.outputs.vaultUri
output vaultResourceId string = providerCredentialKeyVault.outputs.vaultResourceId
