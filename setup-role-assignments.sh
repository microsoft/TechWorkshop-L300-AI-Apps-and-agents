#!/bin/bash
#
# setup-role-assignments.sh
# Setup managed identity and role assignments for AI Search, Cosmos DB, and Cognitive Services.
#
# Usage (defaults pre-filled, just run):
#   ./setup-role-assignments.sh
#
# Usage (with custom parameters):
#   ./setup-role-assignments.sh RESOURCE_GROUP AI_SEARCH_NAME COSMOS_DB_ACCOUNT_NAME AI_FOUNDRY_NAME AI_PROJECT_NAME
#
# Default values (from your Azure resources):
#   RESOURCE_GROUP: techworkshop-l300-ai-agents1
#   AI_SEARCH_NAME: fsylscyrqnuiq-search
#   COSMOS_DB_ACCOUNT_NAME: fsylscyrqnuiq-cosmosdb
#   AI_FOUNDRY_NAME: aif-fsylscyrqnuiq
#   AI_PROJECT_NAME: proj-fsylscyrqnuiq
#

set -euo pipefail

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

write_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

write_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

write_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

write_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Parse command-line arguments
RESOURCE_GROUP="${1:-techworkshop-l300-ai-agents1}"
AI_SEARCH_NAME="${2:-fsylscyrqnuiq-search}"
COSMOS_DB_ACCOUNT_NAME="${3:-fsylscyrqnuiq-cosmosdb}"
AI_FOUNDRY_NAME="${4:-aif-fsylscyrqnuiq}"
AI_PROJECT_NAME="${5:-proj-fsylscyrqnuiq}"
SKIP_VERIFICATION=false

# Allow override with -v flag for verification skip
if [[ "${6:-}" == "-v" ]]; then
    SKIP_VERIFICATION=true
fi

# Validate required parameters
if [[ -z "$RESOURCE_GROUP" ]] || [[ -z "$AI_SEARCH_NAME" ]] || [[ -z "$COSMOS_DB_ACCOUNT_NAME" ]] || [[ -z "$AI_FOUNDRY_NAME" ]] || [[ -z "$AI_PROJECT_NAME" ]]; then
    write_error "Missing required parameters"
    echo "Usage: $0 [RESOURCE_GROUP] [AI_SEARCH_NAME] [COSMOS_DB_ACCOUNT_NAME] [AI_FOUNDRY_NAME] [AI_PROJECT_NAME] [-v]"
    exit 1
fi

echo -e "\n${MAGENTA}========== Azure Role Assignment Setup ==========${NC}\n"

write_info "Parameters:"
write_info "  Resource Group: $RESOURCE_GROUP"
write_info "  AI Search Name: $AI_SEARCH_NAME"
write_info "  Cosmos DB Account: $COSMOS_DB_ACCOUNT_NAME"
write_info "  AI Foundry Name: $AI_FOUNDRY_NAME"
write_info "  AI Project Name: $AI_PROJECT_NAME"

# Ensure authenticated
write_info "\nChecking Azure CLI authentication..."
if ! az account show --query "id" -o tsv &>/dev/null; then
    write_warning "Not authenticated. Initiating device code login..."
    az login --use-device-code
fi

# Get subscription ID
SUBSCRIPTION_ID=$(az account show --query id -o tsv | xargs)
if [[ -z "$SUBSCRIPTION_ID" ]]; then
    write_error "Failed to retrieve subscription ID"
    exit 1
fi
write_success "Subscription ID: $SUBSCRIPTION_ID"

# Step 1: Get signed-in user principal ID
write_info "\n[1/3] Retrieving signed-in user principal ID..."
PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv | xargs)
if [[ -z "$PRINCIPAL_ID" ]]; then
    write_error "Failed to retrieve user principal ID"
    exit 1
fi
write_success "User Principal ID: $PRINCIPAL_ID"

# Step 2: Enable system-assigned identity on Azure Search
write_info "\n[2/3] Enabling System-Assigned identity on Azure Search service..."
az search service update --resource-group "$RESOURCE_GROUP" --name "$AI_SEARCH_NAME" --set identity.type=SystemAssigned &>/dev/null
write_success "System-Assigned identity enabled"

# Get managed identity principal ID
write_info "Retrieving Azure Search managed identity principal ID..."
AI_SEARCH_MANAGED_IDENTITY_ID=$(az search service show --resource-group "$RESOURCE_GROUP" --name "$AI_SEARCH_NAME" --query identity.principalId -o tsv | xargs)
if [[ -z "$AI_SEARCH_MANAGED_IDENTITY_ID" ]]; then
    write_error "Failed to retrieve Azure Search managed identity"
    exit 1
fi
write_success "Azure Search Managed Identity: $AI_SEARCH_MANAGED_IDENTITY_ID"

# Step 3: Create Cosmos DB and Cognitive Services role assignments
write_info "\n[3/3] Creating role assignments...\n"

# 3a. User Cosmos DB SQL role assignment (Data Contributor)
write_info "  3a. User Cosmos DB SQL role (Data Contributor - 00000000-0000-0000-0000-000000000002)..."
az cosmosdb sql role assignment create \
    --account-name "$COSMOS_DB_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --scope "/" \
    --principal-id "$PRINCIPAL_ID" \
    --role-definition-id "00000000-0000-0000-0000-000000000002" &>/dev/null
write_success "Created"

# 3b. Azure Search managed identity - Cosmos DB Account Reader Role (RBAC)
write_info "  3b. Azure Search Cosmos DB Account Reader (RBAC)..."
COSMOS_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.DocumentDB/databaseAccounts/$COSMOS_DB_ACCOUNT_NAME"
az role assignment create \
    --assignee "$AI_SEARCH_MANAGED_IDENTITY_ID" \
    --role "Cosmos DB Account Reader Role" \
    --scope "$COSMOS_SCOPE" &>/dev/null
write_success "Created"

# 3c. Azure Search managed identity - Cosmos DB SQL role (Data Reader - 00000000-0000-0000-0000-000000000001)
write_info "  3c. Azure Search Cosmos DB SQL role (Data Reader - 00000000-0000-0000-0000-000000000001)..."
az cosmosdb sql role assignment create \
    --account-name "$COSMOS_DB_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --scope "/" \
    --principal-id "$AI_SEARCH_MANAGED_IDENTITY_ID" \
    --role-definition-id "00000000-0000-0000-0000-000000000001" &>/dev/null
write_success "Created"

# 3d. Azure Search managed identity - Cosmos DB SQL role (Data Contributor - 00000000-0000-0000-0000-000000000002)
write_info "  3d. Azure Search Cosmos DB SQL role (Data Contributor - 00000000-0000-0000-0000-000000000002)..."
az cosmosdb sql role assignment create \
    --account-name "$COSMOS_DB_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --scope "/" \
    --principal-id "$AI_SEARCH_MANAGED_IDENTITY_ID" \
    --role-definition-id "00000000-0000-0000-0000-000000000002" &>/dev/null
write_success "Created"

# 3e. Azure Search managed identity - Cognitive Services OpenAI User (Project scope)
write_info "  3e. Azure Search Cognitive Services OpenAI User (Project scope)..."
PROJECT_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$AI_FOUNDRY_NAME/projects/$AI_PROJECT_NAME"
az role assignment create \
    --assignee "$AI_SEARCH_MANAGED_IDENTITY_ID" \
    --role "Cognitive Services OpenAI User" \
    --scope "$PROJECT_SCOPE" &>/dev/null
write_success "Created"

# 3f. Azure Search managed identity - Cognitive Services OpenAI User (Account scope)
write_info "  3f. Azure Search Cognitive Services OpenAI User (Account scope)..."
ACCOUNT_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$AI_FOUNDRY_NAME"
az role assignment create \
    --assignee "$AI_SEARCH_MANAGED_IDENTITY_ID" \
    --role "Cognitive Services OpenAI User" \
    --scope "$ACCOUNT_SCOPE" &>/dev/null
write_success "Created"

# 3g. Azure Search managed identity - Cognitive Services Contributor (Project scope)
write_info "  3g. Azure Search Cognitive Services Contributor (Project scope)..."
az role assignment create \
    --assignee "$AI_SEARCH_MANAGED_IDENTITY_ID" \
    --role "Cognitive Services Contributor" \
    --scope "$PROJECT_SCOPE" &>/dev/null
write_success "Created"

# Verification (optional)
if [[ "$SKIP_VERIFICATION" != "true" ]]; then
    echo -e "\n${MAGENTA}========== Verification ==========${NC}\n"
    
    write_info "Verifying Cosmos DB SQL role assignments for Azure Search..."
    COSMOS_ASSIGNMENTS=$(az cosmosdb sql role assignment list --account-name "$COSMOS_DB_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" --query "[?principalId=='$AI_SEARCH_MANAGED_IDENTITY_ID'] | length(@)" 2>/dev/null)
    if [[ $COSMOS_ASSIGNMENTS -gt 0 ]]; then
        write_success "Found $COSMOS_ASSIGNMENTS Cosmos DB SQL role assignments for Azure Search"
    fi

    write_info "Verifying RBAC role assignments for Azure Search at account scope..."
    RBAC_ASSIGNMENTS=$(az role assignment list --assignee "$AI_SEARCH_MANAGED_IDENTITY_ID" --scope "$ACCOUNT_SCOPE" --query "length(@)" 2>/dev/null)
    if [[ $RBAC_ASSIGNMENTS -gt 0 ]]; then
        write_success "Found $RBAC_ASSIGNMENTS RBAC role assignments for Azure Search"
    fi

    write_success "\nAll role assignments verified!"
fi

echo -e "\n${MAGENTA}========== Setup Complete ==========${NC}\n"
echo -e "${GREEN}Summary:${NC}\n"
echo "  • User Principal ID: $PRINCIPAL_ID"
echo "  • Azure Search Managed Identity: $AI_SEARCH_MANAGED_IDENTITY_ID"
echo "  • Cosmos DB SQL roles: Data Reader, Data Contributor"
echo "  • Cosmos DB RBAC: Account Reader Role"
echo "  • Cognitive Services roles: OpenAI User, Contributor"
echo ""
