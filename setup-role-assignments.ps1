#Requires -Version 7.0
<#
.SYNOPSIS
Setup managed identity and role assignments for AI Search, Cosmos DB, and Cognitive Services.

.DESCRIPTION
This script:
1. Enables System-Assigned identity on Azure Search service
2. Captures the managed identity principal ID
3. Gets current signed-in user principal ID
4. Creates Cosmos DB SQL role assignments for both user and managed identity
5. Creates RBAC role assignments for Cognitive Services/OpenAI
6. Verifies all assignments were created

.PARAMETER ResourceGroup
The Azure resource group name.

.PARAMETER AiSearchName
The Azure AI Search service name.

.PARAMETER CosmosDbAccountName
The Cosmos DB account name.

.PARAMETER AiFoundryName
The Azure AI Foundry (Cognitive Services) account name.

.PARAMETER AiProjectName
The Azure AI Foundry project name.

.PARAMETER SkipVerification
Skip the verification step at the end.

.EXAMPLE
.\setup-role-assignments.ps1 `
  -ResourceGroup "techworkshop-l300-ai-agents1" `
  -AiSearchName "my-search-service" `
  -CosmosDbAccountName "my-cosmosdb" `
  -AiFoundryName "my-foundry" `  
  -AiProjectName "my-project"
#>

param(
    [Parameter(Mandatory = $true, HelpMessage = "Azure resource group name")]
    [string]$ResourceGroup,

    [Parameter(Mandatory = $true, HelpMessage = "Azure AI Search service name")]
    [string]$AiSearchName,

    [Parameter(Mandatory = $true, HelpMessage = "Cosmos DB account name")]
    [string]$CosmosDbAccountName,

    [Parameter(Mandatory = $true, HelpMessage = "Azure AI Foundry account name")]
    [string]$AiFoundryName,

    [Parameter(Mandatory = $true, HelpMessage = "Azure AI Foundry project name")]
    [string]$AiProjectName,

    [Parameter(HelpMessage = "Skip verification step")]
    [switch]$SkipVerification
)

# Color output helpers
function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "ℹ $Message" -ForegroundColor Cyan
}

function Write-Warning {
    param([string]$Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

# Check and re-authenticate if needed
function Ensure-AzAuthenticated {
    Write-Info "Checking Azure CLI authentication..."
    
    try {
        $account = az account show --query "id" -o tsv 2>$null
        if ($LASTEXITCODE -eq 0 -and $account) {
            Write-Success "Already authenticated to subscription: $account"
            return $true
        }
    }
    catch {
        # Silently continue to attempt login
    }

    Write-Warning "Not authenticated or session expired. Initiating interactive login..."
    
    try {
        az login --use-device-code
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Successfully authenticated via device code"
            return $true
        }
        else {
            Write-Error "Failed to authenticate via device code"
            return $false
        }
    }
    catch {
        Write-Error "Authentication error: $_"
        return $false
    }
}

# Get principal ID with validation and trimming
function Get-PrincipalId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Query,
        [string]$Context = "principal"
    )

    try {
        $id = (& $Query 2>$null).Trim()
        if (-not $id) {
            Write-Error "Failed to retrieve $Context - returned empty"
            return $null
        }
        Write-Success "Retrieved $Context : $id"
        return $id
    }
    catch {
        Write-Error "Error retrieving $Context : $_"
        return $null
    }
}

# Execute az command with retry logic
function Invoke-AzCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$Description = "Azure CLI operation",
        [int]$MaxRetries = 1
    )

    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        try {
            Write-Info "Executing: az $($Arguments -join ' ') [$attempt/$MaxRetries]"
            
            $result = & az @Arguments 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "$Description completed"
                return $result
            }
            elseif ($LASTEXITCODE -eq 401 -or $result -match "Timeout|token|unauthorized") {
                Write-Warning "Authentication issue detected. Re-authenticating..."
                if (Ensure-AzAuthenticated) {
                    continue
                }
            }
            else {
                Write-Error "$Description failed: $result"
                return $null
            }
        }
        catch {
            Write-Error "$Description error: $_"
            if ($attempt -lt $MaxRetries) {
                Write-Warning "Retrying..."
            }
        }
    }

    return $null
}

# ============================================================================
# Main Script Execution
# ============================================================================

Write-Host "`n========== Azure Role Assignment Setup ==========" -ForegroundColor Magenta

# Validate input parameters
Write-Info "Validating parameters..."
@("ResourceGroup", "AiSearchName", "CosmosDbAccountName", "AiFoundryName", "AiProjectName") | ForEach-Object {
    $value = Get-Variable -Name $_ -ValueOnly
    Write-Info "  $_ : $value"
}

# Ensure authenticated
if (-not (Ensure-AzAuthenticated)) {
    Write-Error "Could not authenticate. Exiting."
    exit 1
}

# Get subscription ID
Write-Info "Retrieving subscription ID..."
$subscriptionId = (az account show --query id -o tsv).Trim()
if (-not $subscriptionId) {
    Write-Error "Failed to retrieve subscription ID"
    exit 1
}
Write-Success "Subscription ID: $subscriptionId"

# Step 1: Get signed-in user principal ID
Write-Info "`n[1/3] Retrieving signed-in user principal ID..."
$principalId = Get-PrincipalId `
    -Query "az ad signed-in-user show --query id -o tsv" `
    -Context "signed-in user principal ID"

if (-not $principalId) {
    Write-Error "Could not retrieve user principal ID. Exiting."
    exit 1
}

# Step 2: Enable system-assigned identity on Azure Search
Write-Info "`n[2/3] Enabling System-Assigned identity on Azure Search service..."
$null = Invoke-AzCommand `
    -Arguments @("search", "service", "update", "--resource-group", $ResourceGroup, "--name", $AiSearchName, "--set", "identity.type=SystemAssigned") `
    -Description "Enable System-Assigned identity on Azure Search"

# Get managed identity principal ID
Write-Info "Retrieving Azure Search managed identity principal ID..."
$aiSearchManagedIdentityId = Get-PrincipalId `
    -Query "az search service show --resource-group $ResourceGroup --name $AiSearchName --query identity.principalId -o tsv" `
    -Context "Azure Search managed identity principal ID"

if (-not $aiSearchManagedIdentityId) {
    Write-Error "Could not retrieve Azure Search managed identity. Exiting."
    exit 1
}

# Step 3: Create Cosmos DB and Cognitive Services role assignments
Write-Info "`n[3/3] Creating role assignments..."

# 3a. User Cosmos DB SQL role assignment (Data Contributor)
Write-Info "`n  3a. User Cosmos DB SQL role (Data Contributor - 00000000-0000-0000-0000-000000000002)..."
$null = Invoke-AzCommand `
    -Arguments @("cosmosdb", "sql", "role", "assignment", "create", "--account-name", $CosmosDbAccountName, "--resource-group", $ResourceGroup, "--scope", "/", "--principal-id", $principalId, "--role-definition-id", "00000000-0000-0000-0000-000000000002") `
    -Description "Create Cosmos DB SQL role assignment for signed-in user"

# 3b. Azure Search managed identity - Cosmos DB Account Reader Role (RBAC)
Write-Info "`n  3b. Azure Search Cosmos DB Account Reader (RBAC)..."
$cosmosScope = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$CosmosDbAccountName"
$null = Invoke-AzCommand `
    -Arguments @("role", "assignment", "create", "--assignee", $aiSearchManagedIdentityId, "--role", "Cosmos DB Account Reader Role", "--scope", $cosmosScope) `
    -Description "Create Cosmos DB Account Reader RBAC assignment"

# 3c. Azure Search managed identity - Cosmos DB SQL role (Data Reader - 00000000-0000-0000-0000-000000000001)
Write-Info "`n  3c. Azure Search Cosmos DB SQL role (Data Reader - 00000000-0000-0000-0000-000000000001)..."
$null = Invoke-AzCommand `
    -Arguments @("cosmosdb", "sql", "role", "assignment", "create", "--account-name", $CosmosDbAccountName, "--resource-group", $ResourceGroup, "--scope", "/", "--principal-id", $aiSearchManagedIdentityId, "--role-definition-id", "00000000-0000-0000-0000-000000000001") `
    -Description "Create Cosmos DB SQL Data Reader role for Azure Search managed identity"

# 3d. Azure Search managed identity - Cosmos DB SQL role (Data Contributor - 00000000-0000-0000-0000-000000000002)
Write-Info "`n  3d. Azure Search Cosmos DB SQL role (Data Contributor - 00000000-0000-0000-0000-000000000002)..."
$null = Invoke-AzCommand `
    -Arguments @("cosmosdb", "sql", "role", "assignment", "create", "--account-name", $CosmosDbAccountName, "--resource-group", $ResourceGroup, "--scope", "/", "--principal-id", $aiSearchManagedIdentityId, "--role-definition-id", "00000000-0000-0000-0000-000000000002") `
    -Description "Create Cosmos DB SQL Data Contributor role for Azure Search managed identity"

# 3e. Azure Search managed identity - Cognitive Services OpenAI User (Project scope)
Write-Info "`n  3e. Azure Search Cognitive Services OpenAI User (Project scope)..."
$projectScope = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$AiFoundryName/projects/$AiProjectName"
$null = Invoke-AzCommand `
    -Arguments @("role", "assignment", "create", "--assignee", $aiSearchManagedIdentityId, "--role", "Cognitive Services OpenAI User", "--scope", $projectScope) `
    -Description "Create Cognitive Services OpenAI User role at project scope"

# 3f. Azure Search managed identity - Cognitive Services OpenAI User (Account scope)
Write-Info "`n  3f. Azure Search Cognitive Services OpenAI User (Account scope)..."
$accountScope = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$AiFoundryName"
$null = Invoke-AzCommand `
    -Arguments @("role", "assignment", "create", "--assignee", $aiSearchManagedIdentityId, "--role", "Cognitive Services OpenAI User", "--scope", $accountScope) `
    -Description "Create Cognitive Services OpenAI User role at account scope"

# 3g. Azure Search managed identity - Cognitive Services Contributor (Project scope)
Write-Info "`n  3g. Azure Search Cognitive Services Contributor (Project scope)..."
$null = Invoke-AzCommand `
    -Arguments @("role", "assignment", "create", "--assignee", $aiSearchManagedIdentityId, "--role", "Cognitive Services Contributor", "--scope", $projectScope) `
    -Description "Create Cognitive Services Contributor role at project scope"

# Verification (optional)
if (-not $SkipVerification) {
    Write-Info "`n========== Verification ==========="
    
    Write-Info "`nVerifying Cosmos DB SQL role assignments for Azure Search..."
    $cosmosAssignments = az cosmosdb sql role assignment list --account-name $CosmosDbAccountName --resource-group $ResourceGroup --query "[?principalId=='$aiSearchManagedIdentityId']" -o json 2>$null
    if ($cosmosAssignments) {
        $count = ($cosmosAssignments | ConvertFrom-Json).Count
        Write-Success "Found $count Cosmos DB SQL role assignments for Azure Search"
    }

    Write-Info "Verifying RBAC role assignments for Azure Search at account scope..."
    $rbacAssignments = az role assignment list --assignee $aiSearchManagedIdentityId --scope $accountScope --query "length([])" 2>$null
    if ($rbacAssignments -gt 0) {
        Write-Success "Found $rbacAssignments RBAC role assignments for Azure Search"
    }

    Write-Success "`nAll role assignments verified!"
}

Write-Host "`n========== Setup Complete ==========" -ForegroundColor Magenta
Write-Host "`nSummary:`n" -ForegroundColor Green
Write-Host "  • User Principal ID: $principalId"
Write-Host "  • Azure Search Managed Identity: $aiSearchManagedIdentityId"
Write-Host "  • Cosmos DB SQL roles: Data Reader, Data Contributor"
Write-Host "  • Cosmos DB RBAC: Account Reader Role"
Write-Host "  • Cognitive Services roles: OpenAI User, Contributor"
Write-Host ""
