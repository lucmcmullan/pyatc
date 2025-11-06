import requests, json, re

GH_API = "https://raw.githubusercontent.com/lucmcmullan/pyatc/versions.txt"

def fetch_remote_version() -> str | None:
    """Get the current version string from the Versions file on GitHub."""
    try:
        response = requests.get(GH_API, timeout=5)
        response.raise_for_status()
        text = response.text

        # Look for a line like: Current - v1.6.3
        match = re.search(r"Current\s*-\s*v?([\d.]+)", text)
        if match:
            return f"v{match.group(1)}"
    except Exception:
        pass
    return None


def check_for_update(local_version: str) -> tuple[bool, str | None]:
    """Compare the local version to the remote one."""
    remote = fetch_remote_version()
    if not remote:
        return False, None

    local_clean = local_version.lstrip("v")
    remote_clean = remote.lstrip("v")
    return (remote_clean != local_clean, remote)