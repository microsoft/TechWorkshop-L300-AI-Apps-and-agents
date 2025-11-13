# Azure RBAC Configuration Script
$resourceGroup = "YOUR_RESOURCE_GROUP_NAME"
$cosmosDbAccountName = "YOUR_COSMOSDB_NAME"
$aiSearchName = "YOUR_AI_SEARCH_NAME"
$aiFoundryName = "YOUR_AI_FOUNDRY_NAME"
$aiProjectName = "YOUR_AI_PROJECT_NAME"

# Get user's principal ID
$principalId = az ad signed-in-user show --query id -o tsv

# Set SystemAssigned managed identity for AI Search
Write-Host "Setting managed identity for AI Search service..."
az search service update --resource-group $resourceGroup --name $aiSearchName --set identity.type=SystemAssigned

# Get principal ID of AI Search managed identity
Write-Host "Getting principal ID of AI Search managed identity..."
$aiSearchManagedIdentityId = az search service show --resource-group $resourceGroup --name $aiSearchName --query identity.principalId -o tsv

# Grant read/write permissions for Cosmos DB to user
Write-Host "Setting Cosmos DB permissions for user..."
az cosmosdb sql role assignment create --account-name $cosmosDbAccountName --resource-group $resourceGroup --scope "/" --principal-id $principalId --role-definition-id "00000000-0000-0000-0000-000000000002"

# Grant Cosmos DB Account Reader Role to AI Search managed identity
Write-Host "Setting Cosmos DB Account Reader Role for AI Search..."
$subscriptionId = az account show --query id -o tsv
az role assignment create --assignee $aiSearchManagedIdentityId --role "Cosmos DB Account Reader Role" --scope "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$cosmosDbAccountName"

# Grant read/write permissions for Cosmos DB to AI Search managed identity
Write-Host "Setting Cosmos DB permissions for AI Search..."
az cosmosdb sql role assignment create --account-name $cosmosDbAccountName --resource-group $resourceGroup --scope "/" --principal-id $aiSearchManagedIdentityId --role-definition-id "00000000-0000-0000-0000-000000000001"
az cosmosdb sql role assignment create --account-name $cosmosDbAccountName --resource-group $resourceGroup --scope "/" --principal-id $aiSearchManagedIdentityId --role-definition-id "00000000-0000-0000-0000-000000000002"

# Grant AI Foundry permissions to AI Search managed identity
Write-Host "Setting AI Foundry permissions for AI Search..."
az role assignment create --assignee $aiSearchManagedIdentityId --role "Cognitive Services OpenAI User" --scope "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.CognitiveServices/accounts/$aiFoundryName"
az role assignment create --assignee $aiSearchManagedIdentityId --role "Cognitive Services Contributor" --scope "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.CognitiveServices/accounts/$aiFoundryName"

Write-Host "RBAC configuration completed."