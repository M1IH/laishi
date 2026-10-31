from __future__ import annotations

import json
from typing import Any

import aiohttp


class AnySearchError(RuntimeError):
    """Raised when AnySearch returns an HTTP or JSON-RPC error."""


TRUNCATE_NOTICE = (
    "\n\n[已截断：原始返回 {total} 字符，只保留前 {kept} 字符。"
    "需要更多细节就用更窄的关键词再搜一次，不要一次吞全文。]"
)


def _truncate(text: str, max_chars: int | None) -> str:
    """Limit tool output size so search results cannot flood the context."""
    if not max_chars or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + TRUNCATE_NOTICE.format(
        total=len(text), kept=max_chars
    )


class AnySearchClient:
    endpoint = "https://api.anysearch.com/mcp"

    def __init__(
        self,
        api_key: str = "",
        timeout: int = 30,
        tool_result_max_chars: int = 4000,
    ) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        try:
            self.tool_result_max_chars = int(tool_result_max_chars)
        except (TypeError, ValueError):
            self.tool_result_max_chars = 4000

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            try:
                async with session.post(
                    self.endpoint,
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    text = await response.text()
                    if response.status >= 400:
                        raise AnySearchError(
                            f"AnySearch HTTP {response.status}: {text[:500]}"
                        )
            except TimeoutError as exc:
                raise AnySearchError("AnySearch request timed out.") from exc
            except aiohttp.ClientError as exc:
                raise AnySearchError(f"AnySearch connection failed: {exc}") from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnySearchError(f"AnySearch returned invalid JSON: {text[:500]}") from exc

        if "error" in data:
            error = data["error"]
            if isinstance(error, dict):
                message = error.get("message") or json.dumps(error, ensure_ascii=False)
            else:
                message = str(error)
            raise AnySearchError(f"AnySearch API error: {message}")

        result = data.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    return str(item.get("text", ""))

        return json.dumps(result, ensure_ascii=False, indent=2)

    async def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        freshness: str = "",
        content_types: list[str] | None = None,
    ) -> str:
        arguments: dict[str, Any] = {"query": query}
        if max_results is not None:
            arguments["max_results"] = max_results
        if freshness:
            arguments["freshness"] = freshness
        if content_types:
            arguments["content_types"] = content_types
        text = await self._call("search", arguments)
        return _truncate(text, self.tool_result_max_chars)

    async def vertical_search(
        self,
        query: str,
        *,
        domain: str,
        sub_domain: str,
        zone: str = "",
        max_results: int | None = None,
        freshness: str = "",
        content_types: list[str] | None = None,
        sub_domain_params: dict[str, Any] | None = None,
    ) -> str:
        arguments: dict[str, Any] = {
            "query": query,
            "domain": domain,
            "sub_domain": sub_domain,
        }
        if zone:
            arguments["zone"] = zone
        if max_results is not None:
            arguments["max_results"] = max_results
        if freshness:
            arguments["freshness"] = freshness
        if content_types:
            arguments["content_types"] = content_types
        if sub_domain_params:
            arguments["sub_domain_params"] = sub_domain_params
        return await self._call("search", arguments)

    async def list_domains(
        self,
        *,
        domain: str = "",
        domains: list[str] | None = None,
    ) -> str:
        if domains:
            return await self._call("list_domains", {"domains": domains})
        return await self._call("list_domains", {"domain": domain})

    async def batch_search(self, queries: list[dict[str, Any]]) -> str:
        text = await self._call("batch_search", {"queries": queries})
        budget = self.tool_result_max_chars * max(1, len(queries))
        return _truncate(text, min(budget, 20000))

    async def extract(self, url: str) -> str:
        text = await self._call("extract", {"url": url})
        return _truncate(text, self.tool_result_max_chars)
