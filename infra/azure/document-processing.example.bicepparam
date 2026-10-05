using './document-processing.bicep'

param serviceBusNamespaceName = 'nexus-service-bus'
param dispatcherPrincipalId = ''
// Leave the receiver role and consumer deployment inactive until a real processor exists.
param workerPrincipalId = ''
