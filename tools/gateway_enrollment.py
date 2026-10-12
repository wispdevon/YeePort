"""Enrollment endpoint diagnostics; sends no application credentials."""

import asyncio
import re
from urllib.parse import urlsplit


def enrollment_endpoint(configuration):
    params = configuration.get("params")
    if not isinstance(params, dict):
        raise ValueError("Configuration params must be an object")
    server, port = params.get("server"), params.get("port")
    if not isinstance(server, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", server):
        raise ValueError("Unsupported enrollment server format")
    if isinstance(port, str) and port.isdecimal():
        port = int(port)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Invalid enrollment port")
    url = params.get("url")
    api_host = urlsplit(url).hostname if isinstance(url, str) else None
    return server, port, api_host


async def probe_endpoint(configuration):
    server, port, api_host = enrollment_endpoint(configuration)
    result = {"server": server, "port": port, "api_host": api_host,
              "enrollment_complete": False}
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), 7)
        result["reachable"] = True
        try:
            data = await asyncio.wait_for(reader.read(256), 2)
            result["server_initial_bytes"] = len(data)
        except TimeoutError:
            result["server_initial_bytes"] = 0
    except (OSError, TimeoutError):
        result["reachable"] = False
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
    return result
