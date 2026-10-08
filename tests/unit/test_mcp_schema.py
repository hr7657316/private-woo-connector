"""Drives the MCP server in-process through the official client: what a host actually sees."""

import json

import httpx
import pytest
import respx
from mcp import Client

from woo_connector import mcp_server
from woo_connector.mcp_server import server

EXPECTED_TOOLS = {
    "list_orders",
    "get_order",
    "search_orders",
    "list_order_statuses",
    "list_products",
    "get_product",
    "search_products",
    "get_stock",
    "list_low_stock",
}


@pytest.fixture
async def configured(monkeypatch):
    monkeypatch.setenv("WOO_BASE_URL", "https://shop.example.com")
    monkeypatch.setenv("WOO_CONSUMER_KEY", "ck_test")
    monkeypatch.setenv("WOO_CONSUMER_SECRET", "cs_test")
    monkeypatch.setenv("WOO_MAX_RETRIES", "0")
    await mcp_server.reset_client()
    yield
    await mcp_server.reset_client()


async def test_tool_list_matches_spec():
    async with Client(server) as client:
        result = await client.list_tools()
    tools = {t.name: t for t in result.tools}
    assert set(tools) == EXPECTED_TOOLS

    assert tools["get_order"].input_schema["required"] == ["order_id"]
    assert "required" not in tools["list_orders"].input_schema or "status" not in tools["list_orders"].input_schema["required"]
    assert tools["list_orders"].input_schema["properties"]["per_page"]["maximum"] == 100
    assert tools["search_orders"].input_schema["properties"]["query"]["minLength"] == 1

    for tool in tools.values():
        assert tool.description, f"{tool.name} has no description"
        assert tool.annotations and tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


@respx.mock
async def test_call_tool_returns_trimmed_order(configured, sample_order):
    respx.get("https://shop.example.com/wp-json/wc/v3/orders/1042").mock(
        return_value=httpx.Response(200, json=sample_order, headers={"Content-Type": "application/json"})
    )
    async with Client(server) as client:
        result = await client.call_tool("get_order", {"order_id": 1042})
    assert result.is_error is False
    payload = result.structured_content or json.loads(result.content[0].text)
    assert payload["number"] == "1042"
    assert payload["customer"]["name"] == "Priya Nair"
    assert "meta_data" not in payload


@respx.mock
async def test_store_errors_surface_as_tool_errors(configured):
    respx.get("https://shop.example.com/wp-json/wc/v3/orders/999").mock(
        return_value=httpx.Response(404, json={"code": "woocommerce_rest_shop_order_invalid_id", "message": "Invalid ID."})
    )
    async with Client(server) as client:
        result = await client.call_tool("get_order", {"order_id": 999})
    assert result.is_error is True
    assert "Invalid ID" in result.content[0].text


async def test_invalid_arguments_are_rejected_before_any_http(configured):
    async with Client(server) as client:
        result = await client.call_tool("list_orders", {"per_page": 500})
    assert result.is_error is True


async def test_missing_configuration_is_explained(monkeypatch):
    for key in ("WOO_BASE_URL", "WOO_CONSUMER_KEY", "WOO_CONSUMER_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mcp_server.Settings, "model_config", {**mcp_server.Settings.model_config, "env_file": None})
    await mcp_server.reset_client()
    async with Client(server) as client:
        result = await client.call_tool("list_order_statuses", {})
    assert result.is_error is True
    assert "WOO_BASE_URL" in result.content[0].text
