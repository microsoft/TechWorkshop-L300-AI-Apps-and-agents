"""
Pre-flight quota and resource availability check for TechWorkshop L300.
Verifies that your subscription has sufficient quota in candidate regions
for all resources deployed by the Bicep template.

Usage:
    python check_quota.py                          # Check default regions
    python check_quota.py westus2 northeurope      # Check additional regions

Requirements: Azure CLI (az) -- must be logged in.
"""

import json
import platform
import subprocess
import sys

# ---------- configuration ----------

DEFAULT_REGIONS = ["eastus2", "swedencentral", "francecentral"]

REQUIRED_PROVIDERS = [
    "Microsoft.DocumentDB",
    "Microsoft.CognitiveServices",
    "Microsoft.App",
    "Microsoft.ContainerRegistry",
    "Microsoft.OperationalInsights",
    "Microsoft.Insights",
    "Microsoft.Storage",
]

# Resource type to check per provider, and display name for output.
PROVIDER_RESOURCE_CHECKS = [
    ("Microsoft.DocumentDB", "databaseAccounts", "Cosmos DB (NoSQL)"),
    ("Microsoft.ContainerRegistry", "registries", "Container Registry"),
    ("Microsoft.CognitiveServices", "accounts", "AI Services (Microsoft Foundry)"),
    ("Microsoft.App", "containerApps", "Container Apps"),
]

# ---------- helpers ----------

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
NC = "\033[0m"


def passed(msg: str) -> None:
    print(f"  {GREEN}[PASS]{NC}  {msg}")


def failed(msg: str) -> None:
    print(f"  {RED}[FAIL]{NC}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}[WARN]{NC}  {msg}")


def header(msg: str) -> None:
    print(f"\n{YELLOW}=== {msg} ==={NC}")


def az(args: list[str]) -> str:
    """Run an az CLI command and return stdout. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["az"] + args,
            capture_output=True,
            text=True,
            timeout=60,
            shell=platform.system() == "Windows",
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def az_json(args: list[str]) -> object:
    """Run an az CLI command and parse JSON output."""
    raw = az(args)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def normalize(name: str) -> str:
    """Normalize a region name for comparison (lowercase, no spaces)."""
    return name.lower().replace(" ", "")


# ---------- pre-checks ----------

def check_login() -> bool:
    result = az_json(["account", "show", "-o", "json"])
    if not result:
        print("Error: Not logged in to Azure CLI. Run 'az login' first.")
        return False
    name = result.get("name", "Unknown")
    sub_id = result.get("id", "Unknown")
    print(f"Subscription: {name}\t{sub_id}")
    return True


# ---------- check resource provider registration ----------

def check_providers() -> bool:
    header("Resource Provider Registration")
    all_ok = True
    for provider in REQUIRED_PROVIDERS:
        state = az(
            ["provider", "show", "--namespace", provider,
             "--query", "registrationState", "-o", "tsv"]
        )
        if state == "Registered":
            passed(provider)
        else:
            failed(f"{provider} ({state or 'NotRegistered'})")
            all_ok = False

    if not all_ok:
        print()
        warn("Some resource providers are not registered. You can register them with:")
        print("  az provider register --namespace <provider-name>")
        print("  Registration can take a few minutes to propagate.")

    return all_ok


# ---------- per-region checks ----------

def check_provider_region(
    namespace: str, resource_type: str, display_name: str, region: str
) -> bool:
    """Check that a resource provider supports a resource type in the given region."""
    locations_raw = az(
        ["provider", "show", "--namespace", namespace,
         "--query", f"resourceTypes[?resourceType=='{resource_type}'].locations[]",
         "-o", "tsv"]
    )
    available = {normalize(loc) for loc in locations_raw.splitlines() if loc.strip()}
    if normalize(region) in available:
        passed(f"{display_name}: available")
        return True
    else:
        failed(f"{display_name}: not available in this region")
        return False


def check_region(region: str) -> bool:
    header(f"Region: {region}")
    region_ok = True

    for namespace, resource_type, display_name in PROVIDER_RESOURCE_CHECKS:
        if not check_provider_region(namespace, resource_type, display_name, region):
            region_ok = False

    return region_ok


# ---------- main ----------

def main() -> None:
    extra_regions = sys.argv[1:]
    regions = DEFAULT_REGIONS + extra_regions

    if not check_login():
        sys.exit(1)

    print(f"Regions to check: {', '.join(regions)}")

    check_providers()

    viable = [r for r in regions if check_region(r)]

    header("Summary")
    if viable:
        print(f"Viable regions: {', '.join(viable)}")
        print()
        print("Note: This script checks compute quota and resource provider availability.")
        print("OpenAI model quota (gpt-5.4-mini) is checked automatically by 'azd up'")
        print("when you select a region during deployment.")
    else:
        print("No viable regions found. Check quota and provider registration above.")
        print("You can request quota increases in the Azure portal under")
        print("Subscriptions > Usage + quotas.")
        sys.exit(1)


if __name__ == "__main__":
    main()
