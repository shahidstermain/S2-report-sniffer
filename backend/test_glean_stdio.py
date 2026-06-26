#!/usr/bin/env python3
"""
Test script for Glean MCP stdio connection.
"""
import asyncio
import os

import pytest

# This module is a live integration script: it connects to the Glean MCP
# endpoint over the network and is normally run via `python test_glean_stdio.py`.
# It is not part of the offline core test gate, so skip it under pytest unless
# explicitly enabled.
if os.environ.get("S2RS_RUN_LIVE_GLEAN") != "1":
    pytest.skip(
        "live Glean MCP integration script; run manually or set S2RS_RUN_LIVE_GLEAN=1",
        allow_module_level=True,
    )

from glean_mcp import GleanMCPClient

async def test_stdio_connection():
    """Test stdio MCP connection."""
    print("Testing Glean MCP stdio connection...")
    
    # Create client with stdio mode (use_remote=False)
    client = GleanMCPClient(
        base_url="https://singlestore-be.glean.com",
        api_token="",
        port=3000,
        use_remote=False,
        timeout=30
    )
    
    # Test health check
    print("\n1. Testing health check...")
    health_result = await client.health_check()
    print(f"   Health check result: {health_result}")
    
    if health_result.get("status") == "ok":
        print("   ✅ Health check passed")
    else:
        print(f"   ❌ Health check failed: {health_result.get('message')}")
        return False
    
    # Test search
    print("\n2. Testing search...")
    try:
        insights = await client.fetch_related_insights(
            query="SingleStore replication lag",
            datasource="cases"
        )
        print(f"   Found {len(insights)} insights")
        if insights:
            print(f"   First insight: {insights[0].get('title', 'N/A')}")
            print("   ✅ Search test passed")
        else:
            print("   ⚠️  Search returned no results (may be expected)")
    except Exception as e:
        print(f"   ❌ Search test failed: {e}")
        return False
    
    print("\n✅ All tests passed")
    return True

if __name__ == "__main__":
    asyncio.run(test_stdio_connection())
