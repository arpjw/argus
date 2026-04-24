from typing import Optional

from fastapi import Header, HTTPException, Query

from argus import config


async def verify_api_key(
    x_api_key: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None),
):
    if not config.ARGUS_API_KEY:
        return  # dev mode — no key set, pass through
    key = x_api_key or api_key
    if key != config.ARGUS_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
