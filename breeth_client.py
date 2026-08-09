"""Client for Breeth semantic memory integration."""
import os
import logging
import httpx
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

BREETH_API_KEY = os.getenv("BREETH_API_KEY")
BREETH_BASE_URL = os.getenv("BREETH_BASE_URL", "https://api.breeth.ai/v1")

async def get_semantic_memories(agent_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve past semantic memories for an agent from Breeth."""
    if not BREETH_API_KEY:
        logger.debug(f"Breeth retrieval skipped for agent {agent_id} (API key not configured)")
        return []

    url = f"{BREETH_BASE_URL}/agents/{agent_id}/memories"
    headers = {
        "Authorization": f"Bearer {BREETH_API_KEY}",
        "Content-Type": "application/json"
    }
    params = {"limit": limit}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get("memories", [])
            else:
                logger.warning(f"Breeth memory fetch failed with status {response.status_code}: {response.text}")
                return []
    except Exception as e:
        logger.warning(f"Breeth retrieval exception for agent {agent_id}: {e}")
        return []

async def write_memory(agent_id: str, text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Write a new post memory back into Breeth storage."""
    if not BREETH_API_KEY:
        logger.debug(f"Breeth write skipped for agent {agent_id} (API key not configured)")
        return {"success": False, "error": "API key not configured"}

    url = f"{BREETH_BASE_URL}/agents/{agent_id}/memories"
    headers = {
        "Authorization": f"Bearer {BREETH_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "metadata": metadata
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code in (200, 201):
                return {"success": True, "agent_id": agent_id}
            else:
                logger.warning(f"Breeth memory write failed with status {response.status_code}: {response.text}")
                return {"success": False, "error": response.text}
    except Exception as e:
        logger.warning(f"Breeth write exception for agent {agent_id}: {e}")
        return {"success": False, "error": str(e)}