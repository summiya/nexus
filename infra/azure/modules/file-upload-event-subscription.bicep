metadata description = 'Adds the Nexus File BlobCreated subscription to an explicitly selected shared system topic.'

param systemTopicName string
param eventSubscriptionName string
param queueResourceId string
param deadLetterStorageAccountId string
param deadLetterContainerName string
param fileContainerName string

var fileSubjectPrefix = '/blobServices/default/containers/${fileContainerName}/blobs/files/'

resource systemTopic 'Microsoft.EventGrid/systemTopics@2025-02-15' existing = {
  name: systemTopicName
}

resource eventSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2025-02-15' = {
  name: eventSubscriptionName
  parent: systemTopic
  properties: {
    deadLetterWithResourceIdentity: {
      deadLetterDestination: {
        endpointType: 'StorageBlob'
        properties: {
          blobContainerName: deadLetterContainerName
          resourceId: deadLetterStorageAccountId
        }
      }
      identity: {
        type: 'SystemAssigned'
      }
    }
    deliveryWithResourceIdentity: {
      destination: {
        endpointType: 'ServiceBusQueue'
        properties: {
          resourceId: queueResourceId
        }
      }
      identity: {
        type: 'SystemAssigned'
      }
    }
    eventDeliverySchema: 'CloudEventSchemaV1_0'
    filter: {
      advancedFilters: []
      includedEventTypes: [
        'Microsoft.Storage.BlobCreated'
      ]
      isSubjectCaseSensitive: true
      subjectBeginsWith: fileSubjectPrefix
      subjectEndsWith: ''
    }
    labels: [
      'nexus-files'
    ]
    retryPolicy: {
      eventTimeToLiveInMinutes: 1440
      maxDeliveryAttempts: 30
    }
  }
}

output eventSubscriptionResourceId string = eventSubscription.id
