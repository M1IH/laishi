"""Set conservative scheduling for an explicitly selected QQ private session.

Existing prompt and context fields are deliberately preserved. A different
recipient requires --force-target, so rerunning this script cannot silently
replace either the current copy or the selected contact.
"""

import argparse

from miruku_client import api, get_token, latest_private_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qq", required=True, help="QQ private-session number")
    parser.add_argument(
        "--force-target",
        action="store_true",
        help="explicitly replace an existing proactive recipient",
    )
    args = parser.parse_args()

    _, user_id = latest_private_session(args.qq)

    token = get_token()
    current = api(
        "GET", "/plugins/config?plugin_id=astrbot_plugin_proactive_chat", token
    )["config"]
    friend = current["friend_settings"]
    targets = friend.get("session_list", [])
    if targets and targets != [user_id] and not args.force_target:
        raise SystemExit("Existing recipient differs; use --force-target to change it")
    if not friend.get("proactive_prompt", "").strip():
        raise SystemExit("Proactive prompt is empty; refusing to configure scheduling")

    before_prompt = friend["proactive_prompt"]
    before_context = friend.get("context_settings")
    friend["session_list"] = [user_id]
    friend["schedule_settings"]["min_interval_minutes"] = 180
    friend["schedule_settings"]["max_interval_minutes"] = 360
    friend["schedule_settings"]["max_unanswered_times"] = 1
    friend["schedule_settings"]["quiet_hours"] = "1-8"
    assert friend["proactive_prompt"] == before_prompt
    assert friend.get("context_settings") == before_context
    api(
        "PUT",
        "/plugins/config",
        token,
        {"plugin_id": "astrbot_plugin_proactive_chat", "config": current},
    )
    verified = api(
        "GET", "/plugins/config?plugin_id=astrbot_plugin_proactive_chat", token
    )["config"]["friend_settings"]
    if verified["proactive_prompt"] != before_prompt or verified.get("context_settings") != before_context:
        raise RuntimeError("Prompt or context changed during configuration")
    if verified["session_list"] != [user_id]:
        raise RuntimeError("Recipient did not persist")
    print("Proactive scheduling configured; prompt, context and recipient verified")


if __name__ == "__main__":
    main()
