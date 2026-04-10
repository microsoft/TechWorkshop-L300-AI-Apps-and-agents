@description('Object ID of the user/principal to grant Cosmos DB data access')
// Get your principal object ID via: az ad signed-in-user show --query id -o tsv
param userPrincipalId string = deployer().objectId

@minLength(1)
@description('Primary location for all resources. Recommended regions: eastus2, swedencentral, francecentral.')
@metadata({
  azd: {
    type: 'location'
    usageName: [
      'OpenAI.GlobalStandard.gpt-5.4-mini, 50'
    ]
  }
})
param location string = resourceGroup().location

var cosmosDbName = '${uniqueString(resourceGroup().id)}-cosmosdb'
var cosmosDbDatabaseName = 'zava'
var storageAccountName = '${uniqueString(resourceGroup().id)}sa'
var aiFoundryName = 'aif-${uniqueString(resourceGroup().id)}'
var aiProjectName = 'proj-${uniqueString(resourceGroup().id)}'
var containerAppName = 'app-${uniqueString(resourceGroup().id)}'
var containerAppEnvName = '${uniqueString(resourceGroup().id)}-cosu-cae'
var logAnalyticsName = '${uniqueString(resourceGroup().id)}-cosu-la'
var appInsightsName = '${uniqueString(resourceGroup().id)}-cosu-ai'
var registryName = '${uniqueString(resourceGroup().id)}cosureg'
var registrySku = 'Standard'

var tags = {
  Project: 'Tech Workshop L300 - AI Apps and Agents'
  Environment: 'Lab'
  Owner: deployer().userPrincipalName
  SecurityControl: 'ignore'
  CostControl: 'ignore'
}

// Ensure the current resource group has the required tag via a subscription-scoped module
module updateRgTags 'updateRgTags.bicep' = {
  name: 'updateRgTags'
  scope: subscription()
  params: {
    rgName: resourceGroup().name
    rgLocation: resourceGroup().location
    newTags: union(resourceGroup().tags ?? {}, tags )
  }
}

var locations = [
  {
    locationName: location
    failoverPriority: 0
    isZoneRedundant: false
  }
]

@description('Creates an Azure Cosmos DB NoSQL account.')
resource cosmosDbAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: cosmosDbName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  kind: 'GlobalDocumentDB'
  properties: {
    capabilities: [
      {
        name: 'EnableNoSQLVectorSearch'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    databaseAccountOfferType: 'Standard'
    locations: locations
    disableLocalAuth: false
  }
  tags: tags
}

@description('Creates an Azure Cosmos DB NoSQL API database.')
resource cosmosDbDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-04-15' = {
  parent: cosmosDbAccount
  name: cosmosDbDatabaseName
  properties: {
    resource: {
      id: cosmosDbDatabaseName
    }
  }
  tags: tags
}

@description('Creates an Azure Storage account.')
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
  }
  tags: tags
}

resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-10-01-preview' = {
  name: aiFoundryName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'S0'
  }
  kind: 'AIServices'
  properties: {
    // required to work in Microsoft Foundry
    allowProjectManagement: true 

    // Defines developer API endpoint subdomain
    customSubDomainName: aiFoundryName

    disableLocalAuth: false
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

/*
  Developer APIs are exposed via a project, which groups in- and outputs that relate to one use case, including files.
  Its advisable to create one project right away, so development teams can directly get started.
  Projects may be granted individual RBAC permissions and identities on top of what account provides.
*/ 
resource aiProject 'Microsoft.CognitiveServices/accounts/projects@2025-10-01-preview' = {
  name: aiProjectName
  parent: aiFoundry
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
  tags: tags
}

@description('Creates an Azure Log Analytics workspace.')
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 90
    workspaceCapping: {
      dailyQuotaGb: 1
    }
  }
  tags: tags
}

@description('Creates an Azure Application Insights resource.')
resource appInsights 'Microsoft.Insights/components@2020-02-02-preview' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
  }
  tags: tags
}

@description('Creates an Azure Container Registry.')
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2022-12-01' = {
  name: registryName
  location: location
  sku: {
    name: registrySku
  }
  properties: {
    adminUserEnabled: true
  }
  tags: tags
}

@description('Creates an Azure Container Apps Environment.')
resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
  tags: tags
}

// AcrPull role ID
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

@description('Grants the Container App managed identity AcrPull on the Container Registry.')
resource containerAppAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, containerApp.id, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Creates an Azure Container App for Zava.')
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
      }
      secrets: [
        {
          name: 'applicationinsights-connection-string'
          value: appInsights.properties.ConnectionString
        }
      ]
      registries: []
    }
    template: {
      containers: [
        {
          name: 'chat-app'
          image: 'mcr.microsoft.com/k8se/quickstart:latest'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            // Auto-configured from deployed resources
            { name: 'COSMOS_ENDPOINT', value: cosmosDbAccount.properties.documentEndpoint }
            { name: 'storage_account_name', value: storageAccount.name }
            { name: 'DATABASE_NAME', value: cosmosDbDatabaseName }
            { name: 'CONTAINER_NAME', value: 'product_catalog' }
            { name: 'storage_container_name', value: 'zava' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'applicationinsights-connection-string' }
            // Telemetry
            { name: 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT', value: 'true' }
            { name: 'AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED', value: 'true' }
            // Model deployment defaults (names and API versions)
            { name: 'FOUNDRY_API_VERSION', value: '2025-01-01-preview' }
            { name: 'gpt_deployment', value: 'gpt-5.4-mini' }
            { name: 'gpt_api_version', value: '2025-01-01-preview' }
            { name: 'embedding_deployment', value: 'text-embedding-3-large' }
            { name: 'embedding_api_version', value: '2025-01-01-preview' }
            { name: 'phi_4_deployment', value: 'Phi-4' }
            { name: 'phi_4_api_version', value: '2024-05-01-preview' }
            // Agent IDs
            { name: 'customer_loyalty', value: 'customer-loyalty' }
            { name: 'inventory_agent', value: 'inventory-agent' }
            { name: 'interior_designer', value: 'interior-designer' }
            { name: 'cora', value: 'cora' }
            { name: 'cart_manager', value: 'cart-manager' }
            { name: 'handoff_service', value: 'handoff-service' }
            // NOTE: The following must be set after model deployment via
            // az containerapp update --set-env-vars:
            //   FOUNDRY_ENDPOINT, gpt_endpoint, embedding_endpoint, phi_4_endpoint
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
  tags: tags
}

// Cosmos DB built-in data plane role IDs
// Reference: https://learn.microsoft.com/connectors/documentdb/#microsoft-entra-id-authentication-and-cosmos-db-connector
// var cosmosDbBuiltInDataReaderRoleId = '00000000-0000-0000-0000-000000000001'
var cosmosDbBuiltInDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

// Azure RBAC role IDs
// Reference: https://learn.microsoft.com/azure/role-based-access-control/built-in-roles
// var cosmosDbAccountReaderRoleId = 'fbdf93bf-df7d-467e-a4d2-9458aa1360c8'
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesContributorRoleId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'
var azureAIUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

@description('Assigns Cosmos DB Built-in Data Contributor role to the specified user')
resource cosmosDbDataContributorRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = {
  name: guid(cosmosDbAccount.id, userPrincipalId, cosmosDbBuiltInDataContributorRoleId)
  parent: cosmosDbAccount
  properties: {
    roleDefinitionId: '${cosmosDbAccount.id}/sqlRoleDefinitions/${cosmosDbBuiltInDataContributorRoleId}'
    principalId: userPrincipalId
    scope: cosmosDbAccount.id
  }
}

// Role assignments for deploying user principal
@description('Assigns Azure AI User role to the deploying user on AI Project')
resource userProjectAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiProject.id, userPrincipalId, azureAIUserRoleId)
  scope: aiProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIUserRoleId)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

@description('Assigns Azure AI User role to the deploying user on Microsoft Foundry')
resource userFoundryAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, userPrincipalId, azureAIUserRoleId)
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIUserRoleId)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// Role assignments for Cosmos DB managed identity
@description('Assigns Cognitive Services OpenAI User role to Cosmos DB on AI Project')
resource cosmosDbProjectOpenAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiProject.id, cosmosDbAccount.id, cognitiveServicesOpenAIUserRoleId)
  scope: aiProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: cosmosDbAccount.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Cognitive Services OpenAI User role to Cosmos DB on Microsoft Foundry')
resource cosmosDbFoundryOpenAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, cosmosDbAccount.id, cognitiveServicesOpenAIUserRoleId)
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: cosmosDbAccount.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Cognitive Services Contributor role to Cosmos DB on AI Project')
resource cosmosDbProjectContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiProject.id, cosmosDbAccount.id, cognitiveServicesContributorRoleId)
  scope: aiProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: cosmosDbAccount.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Azure AI User role to Cosmos DB on AI Project')
resource cosmosDbProjectAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiProject.id, cosmosDbAccount.id, azureAIUserRoleId)
  scope: aiProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIUserRoleId)
    principalId: cosmosDbAccount.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Azure AI User role to Cosmos DB on Microsoft Foundry')
resource cosmosDbFoundryAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, cosmosDbAccount.id, azureAIUserRoleId)
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAIUserRoleId)
    principalId: cosmosDbAccount.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Container App role assignments
@description('Assigns Cosmos DB Built-in Data Contributor role to the Container App managed identity')
resource containerAppCosmosDbDataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = {
  name: guid(cosmosDbAccount.id, containerApp.id, cosmosDbBuiltInDataContributorRoleId)
  parent: cosmosDbAccount
  properties: {
    roleDefinitionId: '${cosmosDbAccount.id}/sqlRoleDefinitions/${cosmosDbBuiltInDataContributorRoleId}'
    principalId: containerApp.identity.principalId
    scope: cosmosDbAccount.id
  }
}

@description('Assigns Cognitive Services OpenAI User role to the Container App on AI Project')
resource containerAppProjectOpenAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiProject.id, containerApp.id, cognitiveServicesOpenAIUserRoleId)
  scope: aiProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Cognitive Services OpenAI User role to the Container App on Microsoft Foundry')
resource containerAppFoundryOpenAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, containerApp.id, cognitiveServicesOpenAIUserRoleId)
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output cosmosDbEndpoint string = cosmosDbAccount.properties.documentEndpoint
output storageAccountName string = storageAccount.name
output container_registry_name string = containerRegistry.name
output application_name string = containerApp.name
output application_url string = containerApp.properties.configuration.ingress.fqdn

