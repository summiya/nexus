metadata description = 'Explicitly creates shared Event Grid source infrastructure when the storage account has no system topic.'

@description('Name for the new shared system topic.')
param systemTopicName string

@description('Region of the source storage account.')
param location string

@description('Full resource ID of the existing Nexus storage account.')
param storageAccountResourceId string

@description('Optional ownership and environment tags applied to shared source infrastructure.')
param tags object = {}

resource systemTopic 'Microsoft.EventGrid/systemTopics@2025-02-15' = {
  name: systemTopicName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    source: storageAccountResourceId
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

output principalId string = systemTopic.identity.principalId
output resourceId string = systemTopic.id
