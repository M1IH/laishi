"""Send the local image probe to the most recent AstrBot QQ private session."""

import argparse
from pathlib import Path

import requests

from miruku_client import BASE, auth_headers, get_token, latest_private_session


IMAGE = Path(__file__).resolve().parent / "images" / "stage0-test.png"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qq", required=True, help="OTTO's test QQ number")
    args = parser.parse_args()

    _, user_id = latest_private_session(args.qq)

    headers = auth_headers(get_token())
    with IMAGE.open("rb") as image:
        upload = requests.post(
            BASE + "/api/v1/files",
            headers=headers,
            files={"file": (IMAGE.name, image, "image/png")},
            timeout=30,
        )
    upload.raise_for_status()
    uploaded = upload.json()
    if uploaded.get("status") not in ("ok", "success"):
        raise RuntimeError(uploaded.get("message", "Image upload failed"))
    attachment_id = uploaded["data"]["attachment_id"]
    response = requests.post(
        BASE + "/api/v1/im/messages",
        headers=headers,
        json={"umo": user_id, "message": [{"type": "image", "attachment_id": attachment_id}]},
        timeout=30,
    )
    result = response.json()
    if response.status_code != 200 or result.get("status") not in ("ok", "success"):
        raise RuntimeError(f"Image probe failed: HTTP {response.status_code}: {result.get('message', result.get('detail', 'unknown error'))}")
    print("Image probe sent to the recent QQ private test session")


if __name__ == "__main__":
    main()
