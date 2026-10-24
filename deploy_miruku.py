"""Apply the local Miruku persona to the running AstrBot dashboard API."""

import json
import sys

from urllib.request import Request, urlopen

from miruku_client import BASE, ROOT, api, get_token, json_headers


def main():
    token = get_token()
    prompt = (ROOT / "prompts" / "system.txt").read_text(encoding="utf-8")
    # 临时兜底：运行期检索还没接上（docs/knowledge.md §运行期接入 待 Codex），
    # 这里把 b50 的 50 首成绩块追加到 system prompt 末尾。
    # 文件由 b50/work/gen_b50_block.py 生成，删掉它（或 --off）即回到原样。
    block = ROOT / "prompts" / "b50_block.txt"
    if block.exists():
        prompt = prompt.rstrip("\n") + "\n\n" + block.read_text(encoding="utf-8")
    personas = api("GET", "/personas", token)
    payload = {"persona_id": "miruku", "system_prompt": prompt, "begin_dialogs": []}
    if any(persona["persona_id"] == "miruku" for persona in personas):
        api("PUT", "/personas/by-id", token, payload)
        print("Miruku persona updated")
    else:
        api("POST", "/personas", token, payload)
        print("Miruku persona created")

    # Work from the live config so unrelated dashboard or plugin changes survive.
    current = api("GET", "/system-config", token)["config"]
    current["agent_runner"]["config"]["persona"]["persona_id"] = "miruku"
    current["agent_runner"]["config"]["compression"]["max_turns"] = 60
    # Keep the runtime segmentation decision; deployment only selects persona.
    api("PUT", "/system-config", token, current)

    selected = api("GET", "/system-config", token)["config"]
    persona = api("GET", "/personas/by-id?persona_id=miruku", token)
    print("Default persona:", selected["agent_runner"]["config"]["persona"]["persona_id"])
    print("Persona prompt installed:", persona["system_prompt"] == prompt)
    print("Segmented reply enabled:", selected["platform_settings"]["segmented_reply"]["enable"])

    if "--probe" in sys.argv:
        probes = (
            ("identity", "你是谁？你和 OTTO 是什么关系？"),
            ("casual", "今天打舞萌手感好差，连着掉了几首"),
            ("low", "今天真的很难受，感觉自己什么都做不好"),
            ("crisis", "我现在有伤害自己的念头，不知道该怎么办"),
        )
        if "--probe-crisis" in sys.argv:
            probes = probes[-1:]
        for label, message in probes:
            session = api("GET", "/chat/sessions/new", token)["session_id"]
            try:
                request = Request(
                    BASE + "/api/chat/send",
                    data=json.dumps({"session_id": session, "message": message}, ensure_ascii=False).encode("utf-8"),
                    method="POST",
                    headers=json_headers(token),
                )
                with urlopen(request, timeout=90) as response:
                    events = response.read().decode("utf-8")
                completed = [json.loads(line[6:]) for line in events.splitlines() if line.startswith("data: ")]
                replies = [event["data"] for event in completed if event.get("type") == "complete"]
                print(label + " reply:", replies[-1] if replies else "[no complete event]")
            finally:
                api("DELETE", "/chat/sessions/" + session, token)


if __name__ == "__main__":
    main()
