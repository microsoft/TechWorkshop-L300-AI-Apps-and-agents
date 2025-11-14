@description('Object ID of the user/principal to grant Cosmos DB data access')
param userPrincipalId string

@minLength(1)
@description('Primary location for all resources.')
param location string = resourceGroup().location

var cosmosDbName = '${uniqueString(resourceGroup().id)}-cosmosdb'
var cosmosDbDatabaseName = 'zava'
var storageAccountName = '${uniqueString(resourceGroup().id)}sa'
var aiFoundryName = 'aif-${uniqueString(resourceGroup().id)}'
var aiProjectName = 'proj-${uniqueString(resourceGroup().id)}'
var searchServiceName = '${uniqueString(resourceGroup().id)}-search'
var webAppName = '${uniqueString(resourceGroup().id)}-app'
var appServicePlanName = '${uniqueString(resourceGroup().id)}-cosu-asp'
var logAnalyticsName = '${uniqueString(resourceGroup().id)}-cosu-la'
var appInsightsName = '${uniqueString(resourceGroup().id)}-cosu-ai'
var webAppSku = 'S1'
var registryName = '${uniqueString(resourceGroup().id)}cosureg'
var registrySku = 'Standard'

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
  kind: 'GlobalDocumentDB'
  properties: {
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    databaseAccountOfferType: 'Standard'
    locations: locations
    disableLocalAuth: false
  }
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
}

resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
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
    // required to work in AI Foundry
    allowProjectManagement: true 

    // Defines developer API endpoint subdomain
    customSubDomainName: aiFoundryName

    disableLocalAuth: false
  }
}

/*
  Developer APIs are exposed via a project, which groups in- and outputs that relate to one use case, including files.
  Its advisable to create one project right away, so development teams can directly get started.
  Projects may be granted individual RBAC permissions and identities on top of what account provides.
*/ 
resource aiProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  name: aiProjectName
  parent: aiFoundry
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

@description('Creates an Azure AI Search service.')
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'standard'
  }
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
}

@description('Creates an Azure App Service Plan.')
resource appServicePlan 'Microsoft.Web/serverFarms@2022-09-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  properties: {
    reserved: true
  }
  sku: {
    name: webAppSku
  }
}

@description('Creates an Azure App Service for Zava.')
resource appServiceApp 'Microsoft.Web/sites@2022-09-01' = {
  name: webAppName
  location: location
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    clientAffinityEnabled: false
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerRegistry.name}.azurecr.io/${uniqueString(resourceGroup().id)}/techworkshopl300/zava'
      http20Enabled: true
      minTlsVersion: '1.2'
      appCommandLine: ''
      appSettings: [
        {
          name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE'
          value: 'false'
        }
        {
          name: 'DOCKER_REGISTRY_SERVER_URL'
          value: 'https://${containerRegistry.name}.azurecr.io'
        }
        {
          name: 'DOCKER_REGISTRY_SERVER_USERNAME'
          value: containerRegistry.name
        }
        {
          name: 'DOCKER_REGISTRY_SERVER_PASSWORD'
          value: containerRegistry.listCredentials().passwords[0].value
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
        ]
      }
    }
}

// Cosmos DB built-in data plane role IDs
// Reference: https://learn.microsoft.com/en-us/connectors/documentdb/#microsoft-entra-id-authentication-and-cosmos-db-connector
var cosmosDbBuiltInDataReaderRoleId = '00000000-0000-0000-0000-000000000001'
var cosmosDbBuiltInDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

// Azure RBAC role IDs
// Reference: https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles
var cosmosDbAccountReaderRoleId = 'fbdf93bf-df7d-467e-a4d2-9458aa1360c8'
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesContributorRoleId = '25fbc0a9-bd7c-42a3-aa1a-3b75d497ee68'

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

// Role assignments for AI Search managed identity

@description('Assigns Cosmos DB Account Reader Role to AI Search')
resource searchCosmosDbAccountReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cosmosDbAccount.id, searchService.id, cosmosDbAccountReaderRoleId)
  scope: cosmosDbAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cosmosDbAccountReaderRoleId)
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Cosmos DB Built-in Data Reader role to AI Search')
resource searchCosmosDbDataReaderRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = {
  name: guid(cosmosDbAccount.id, searchService.id, cosmosDbBuiltInDataReaderRoleId)
  parent: cosmosDbAccount
  properties: {
    roleDefinitionId: '${cosmosDbAccount.id}/sqlRoleDefinitions/${cosmosDbBuiltInDataReaderRoleId}'
    principalId: searchService.identity.principalId
    scope: cosmosDbAccount.id
  }
}

@description('Assigns Cosmos DB Built-in Data Contributor role to AI Search')
resource searchCosmosDbDataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = {
  name: guid(cosmosDbAccount.id, searchService.id, cosmosDbBuiltInDataContributorRoleId)
  parent: cosmosDbAccount
  properties: {
    roleDefinitionId: '${cosmosDbAccount.id}/sqlRoleDefinitions/${cosmosDbBuiltInDataContributorRoleId}'
    principalId: searchService.identity.principalId
    scope: cosmosDbAccount.id
  }
}

@description('Assigns Cognitive Services OpenAI User role to AI Search on AI Project')
resource searchProjectOpenAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiProject.id, searchService.id, cognitiveServicesOpenAIUserRoleId)
  scope: aiProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Cognitive Services OpenAI User role to AI Search on AI Foundry')
resource searchFoundryOpenAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, searchService.id, cognitiveServicesOpenAIUserRoleId)
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Assigns Cognitive Services Contributor role to AI Search on AI Project')
resource searchProjectContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiProject.id, searchService.id, cognitiveServicesContributorRoleId)
  scope: aiProject
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesContributorRoleId)
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output cosmosDbEndpoint string = cosmosDbAccount.properties.documentEndpoint
output storageAccountName string = storageAccount.name
output searchServiceName string = searchService.name
output container_registry_name string = containerRegistry.name
output application_name string = appServiceApp.name
output application_url string = appServiceApp.properties.hostNames[0]

