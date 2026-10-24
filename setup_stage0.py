"""Install the bundled proactive chat plugin into the running AstrBot instance."""

from pathlib import Path

import requests

from miruku_client import BASE, INSTANCE, auth_headers, get_token


PLUGIN = Path(__file__).resolve().parent / "data" / "astrbot_plugin_proactive_chat.zip"


def main():
    if (INSTANCE / "data" / "plugins" / "astrbot_plugin_proactive_chat").is_dir():
        print("Proactive chat plugin is already installed")
        return
    with PLUGIN.open("rb") as archive:
        response = requests.post(
            BASE + "/api/plugin/install-upload",
            headers=auth_headers(get_token()),
            files={"file": (PLUGIN.name, archive, "application/zip")},
            data={"ignore_version_check": "false"},
            timeout=180,
        )
    response.raise_for_status()
    result = response.json()
    if result.get("status") not in ("ok", "success"):
        raise RuntimeError(result.get("message", "Plugin installation failed"))
    print("Proactive chat plugin installed:", result.get("message", "success"))


if __name__ == "__main__":
    main()
