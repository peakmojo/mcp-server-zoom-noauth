"""MCP Server for Zoom (No Auth) package."""

__version__ = "0.1.0"

import asyncio
from .server import main as _server_main

def main():
    """Entry point for the package to run the Zoom MCP server."""
    asyncio.run(_server_main()) 