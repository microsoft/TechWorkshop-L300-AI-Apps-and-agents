targetScope = 'subscription'

@description('Name of the resource group to update')
param rgName string

@description('Location of the resource group')
param rgLocation string

@description('Object with tags to apply to the resource group')
param newTags object

resource targetRg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: rgName
  location: rgLocation
  tags: newTags
}

output appliedTags object = targetRg.tags
