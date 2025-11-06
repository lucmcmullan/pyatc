import requests, json, re

GH_API = "https://raw.githubusercontent.com/lucmcmullan/pyatc/refs/heads/main/version.txt?token=GHSAT0AAAAAADOSAFGL3OM4WLZWO7S3WJIW2IMODUA"

def fetch_remote_version() -> str | None:
    """Get the current version string from the Versions file on GitHub."""
    try:
        response = requests.get(GH_API, timeout=5)
        response.raise_for_status()
        version = response.text.strip()
        if version.lower().startswith("v"):
            return version
        
    except Exception:
        pass
    return None


def check_for_update(local_version: str) -> tuple[bool, str | None]:
    remote_version = fetch_remote_version()
    if not remote_version:
        return False, None

    local_clean = local_version.lstrip("v").strip()
    remote_clean = remote_version.lstrip("v").strip()

    return (remote_clean != local_clean, remote_version)