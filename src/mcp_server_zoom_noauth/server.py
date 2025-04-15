import logging
from typing import Any, Dict, List, Optional
import os
from dotenv import load_dotenv
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio
from pydantic import AnyUrl
import json
from datetime import datetime, timedelta
from dateutil.tz import tzlocal
import argparse
import base64
import requests
from requests.exceptions import RequestException
import re

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mcp_server_zoom_noauth')
logger.setLevel(logging.DEBUG)

def convert_datetime_fields(obj: Any) -> Any:
    """Convert any datetime or tzlocal objects to string in the given object"""
    if isinstance(obj, dict):
        return {k: convert_datetime_fields(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_datetime_fields(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, tzlocal):
        # Get the current timezone offset
        offset = datetime.now(tzlocal()).strftime('%z')
        return f"UTC{offset[:3]}:{offset[3:]}"  # Format like "UTC+08:00" or "UTC-05:00"
    return obj

class ZoomClient:
    def __init__(self, access_token: Optional[str] = None, refresh_token: Optional[str] = None, 
                 client_id: Optional[str] = None, client_secret: Optional[str] = None):
        if not access_token and not refresh_token:
            raise ValueError("Either access_token or refresh_token must be provided")
        
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://api.zoom.us/v2"

    def _get_headers(self):
        """Get headers for Zoom API requests"""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def _handle_token_refresh(self, func):
        """Decorator to handle token refresh errors gracefully"""
        try:
            return func()
        except RequestException as e:
            logger.error(f"Request error: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code == 401:  # Unauthorized - token might be expired
                    return json.dumps({
                        "error": "Unauthorized. Token might be expired. Try refreshing your token.",
                        "details": str(e)
                    })
                else:
                    return json.dumps({
                        "error": f"Zoom API error: {status_code}",
                        "details": str(e)
                    })
            return json.dumps({
                "error": "Request to Zoom API failed",
                "details": str(e)
            })

    def refresh_access_token(self, client_id: str, client_secret: str) -> str:
        """Refresh the access token using the refresh token
        
        Args:
            client_id: Zoom OAuth2 client ID
            client_secret: Zoom OAuth2 client secret
        """
        logger.debug(f"Starting refresh_access_token with client_id={client_id[:5]}...")
        
        if not self.refresh_token:
            return json.dumps({
                "error": "No refresh token provided",
                "status": "error"
            })
            
        try:
            # Set client_id and client_secret for refresh
            self.client_id = client_id
            self.client_secret = client_secret
            
            # Prepare refresh token request data
            auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            
            headers = {
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token
            }
            
            logger.debug(f"Making POST request to Zoom OAuth token endpoint with refresh_token={self.refresh_token[:10]}...")
            
            # Make the refresh token request
            response = requests.post(
                "https://zoom.us/oauth/token",
                headers=headers,
                data=data
            )
            
            logger.debug(f"Received response with status code: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                logger.debug(f"Success response body: {response.text}")
                logger.debug("Successfully refreshed token")
                self.access_token = result["access_token"]
                self.refresh_token = result.get("refresh_token", self.refresh_token)
                
                # Calculate expiry time
                expires_in = result.get("expires_in", 3600)  # Default to 1 hour
                expiry = datetime.now() + timedelta(seconds=expires_in)
                
                return json.dumps({
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "expires_at": expiry.isoformat(),
                    "expires_in": expires_in,
                    "status": "success"
                })
            else:
                logger.error(f"Failed to refresh token: {response.status_code}, Response: {response.text}")
                # Return the raw response to help with debugging
                return json.dumps({
                    "error": f"Failed to refresh token. Status code: {response.status_code}",
                    "details": response.text,
                    "raw_response": response.text,
                    "status": "error"
                })
                
        except Exception as e:
            logger.error(f"Exception in refresh_access_token: {str(e)}", exc_info=True)
            return json.dumps({
                "error": str(e),
                "status": "error"
            })

    def list_recordings(self, from_date: Optional[str] = None, to_date: Optional[str] = None, 
                        page_size: int = 30, page_number: int = 1) -> str:
        """List cloud recordings from Zoom
        
        Args:
            from_date: Start date for recording search in 'YYYY-MM-DD' format
            to_date: End date for recording search in 'YYYY-MM-DD' format
            page_size: Number of records to return per page (default: 30, max: 300)
            page_number: Page number to return (default: 1)
            
        Returns:
            JSON string with recordings data
        """
        try:
            # Define the operation
            def _operation():
                logger.debug(f"Fetching recordings with page_size={page_size}, page_number={page_number}")
                
                # Prepare query parameters
                params = {
                    "page_size": min(page_size, 300),  # Zoom API limits to 300 max
                    "page_number": page_number
                }
                
                if from_date:
                    params["from"] = from_date
                if to_date:
                    params["to"] = to_date
                
                # Get user's recordings (me = current authenticated user)
                response = requests.get(
                    f"{self.base_url}/users/me/recordings",
                    headers=self._get_headers(),
                    params=params
                )
                
                if response.status_code != 200:
                    return json.dumps({
                        "error": f"Failed to retrieve recordings. Status code: {response.status_code}",
                        "details": response.text,
                        "status": "error"
                    })
                
                recordings_data = response.json()
                
                # Process and return recordings
                return json.dumps(convert_datetime_fields(recordings_data))
            
            # Execute the operation with token refresh handling
            return self._handle_token_refresh(_operation)
                
        except Exception as e:
            logger.error(f"Exception in list_recordings: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e)})

    def get_recording_details(self, meeting_id: str) -> str:
        """Get detailed information about a specific meeting recording
        
        Args:
            meeting_id: The Zoom meeting ID to get recordings for
            
        Returns:
            JSON string with recording details
        """
        try:
            # Define the operation
            def _operation():
                logger.debug(f"Fetching recording details for meeting_id={meeting_id}")
                
                # Get recording information for meeting
                response = requests.get(
                    f"{self.base_url}/meetings/{meeting_id}/recordings",
                    headers=self._get_headers()
                )
                
                if response.status_code != 200:
                    return json.dumps({
                        "error": f"Failed to retrieve recording details. Status code: {response.status_code}",
                        "details": response.text,
                        "status": "error"
                    })
                
                recording_details = response.json()
                
                # Process and return recording details
                return json.dumps(convert_datetime_fields(recording_details))
            
            # Execute the operation with token refresh handling
            return self._handle_token_refresh(_operation)
                
        except Exception as e:
            logger.error(f"Exception in get_recording_details: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e)})

    def get_meeting_transcript(self, meeting_id: str) -> str:
        """Get transcript for a specific meeting recording
        
        Args:
            meeting_id: The Zoom meeting ID to get transcript for
            
        Returns:
            JSON string with transcript data
        """
        try:
            # Define the operation
            def _operation():
                logger.debug(f"Fetching transcript for meeting_id={meeting_id}")
                
                # First get the recording information to find the transcript file
                recordings_response = requests.get(
                    f"{self.base_url}/meetings/{meeting_id}/recordings",
                    headers=self._get_headers()
                )
                
                if recordings_response.status_code != 200:
                    return json.dumps({
                        "error": f"Failed to retrieve recording information. Status code: {recordings_response.status_code}",
                        "details": recordings_response.text,
                        "status": "error"
                    })
                
                recordings_data = recordings_response.json()
                
                # Find transcript files in recording_files
                transcript_files = []
                if "recording_files" in recordings_data:
                    transcript_files = [file for file in recordings_data["recording_files"] 
                                        if file.get("file_type") == "TRANSCRIPT"]
                
                if not transcript_files:
                    return json.dumps({
                        "error": "No transcript files found for this meeting",
                        "status": "error"
                    })
                
                # Process transcript data
                transcripts = []
                for file in transcript_files:
                    if "download_url" in file:
                        # We need to get the actual transcript content
                        # Note: This may require additional authentication or processing
                        # depending on how Zoom provides transcript data
                        transcript_response = requests.get(
                            file["download_url"],
                            headers=self._get_headers()
                        )
                        
                        if transcript_response.status_code == 200:
                            transcripts.append({
                                "file_id": file.get("id", ""),
                                "file_name": file.get("file_name", ""),
                                "recording_start": file.get("recording_start", ""),
                                "recording_end": file.get("recording_end", ""),
                                "content": transcript_response.text
                            })
                
                return json.dumps({
                    "meeting_id": meeting_id,
                    "topic": recordings_data.get("topic", ""),
                    "meeting_duration": recordings_data.get("duration", 0),
                    "transcripts": convert_datetime_fields(transcripts),
                    "status": "success"
                })
            
            # Execute the operation with token refresh handling
            return self._handle_token_refresh(_operation)
                
        except Exception as e:
            logger.error(f"Exception in get_meeting_transcript: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e)})

async def main():
    """Run the Zoom MCP server."""
    logger.info("Zoom server starting")
    server = Server("zoom-client")

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        return []

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> str:
        if uri.scheme != "zoom":
            raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

        path = str(uri).replace("zoom://", "")
        return ""

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        return [
            types.Tool(
                name="zoom_refresh_token",
                description="Refresh the Zoom OAuth2 access token using the refresh token and client credentials for API access",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "zoom_access_token": {"type": "string", "description": "Zoom OAuth2 access token (optional if expired)"},
                        "zoom_refresh_token": {"type": "string", "description": "Zoom OAuth2 refresh token"},
                        "zoom_client_id": {"type": "string", "description": "Zoom OAuth2 client ID for token refresh"},
                        "zoom_client_secret": {"type": "string", "description": "Zoom OAuth2 client secret for token refresh"}
                    },
                    "required": ["zoom_refresh_token", "zoom_client_id", "zoom_client_secret"]
                },
            ),
            types.Tool(
                name="zoom_list_recordings",
                description="List Zoom cloud recordings from a user's Zoom account with pagination support",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "zoom_access_token": {"type": "string", "description": "Zoom OAuth2 access token"},
                        "from_date": {"type": "string", "description": "Start date for Zoom recording search in 'YYYY-MM-DD' format"},
                        "to_date": {"type": "string", "description": "End date for Zoom recording search in 'YYYY-MM-DD' format"},
                        "page_size": {"type": "integer", "description": "Number of Zoom recordings to return per page (default: 30, max: 300)"},
                        "page_number": {"type": "integer", "description": "Page number of Zoom recordings to return (default: 1)"}
                    },
                    "required": ["zoom_access_token"]
                },
            ),
            types.Tool(
                name="zoom_get_recording_details",
                description="Get detailed information about a specific Zoom meeting recording including recording files and metadata",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "zoom_access_token": {"type": "string", "description": "Zoom OAuth2 access token"},
                        "meeting_id": {"type": "string", "description": "The Zoom meeting ID to retrieve recording details for"}
                    },
                    "required": ["zoom_access_token", "meeting_id"]
                },
            ),
            types.Tool(
                name="zoom_get_meeting_transcript",
                description="Get transcript files and content from a specific Zoom meeting recording if available",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "zoom_access_token": {"type": "string", "description": "Zoom OAuth2 access token"},
                        "meeting_id": {"type": "string", "description": "The Zoom meeting ID to retrieve transcript for"}
                    },
                    "required": ["zoom_access_token", "meeting_id"]
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Handle tool execution requests"""
        try:
            # Log the tool name and full arguments for debugging
            logger.debug(f"Tool call: {name}")
            logger.debug(f"Arguments: {json.dumps(arguments) if arguments else None}")
            
            if not arguments:
                raise ValueError(f"Missing arguments for {name}")
                
            # Check if any key in arguments looks like a JSON string but is actually used as a key
            # This happens if the client sends arguments with backticks around keys
            if name == "zoom_refresh_token" and len(arguments) == 1:
                # Try to transform the arguments
                try:
                    key = next(iter(arguments.keys()))
                    logger.debug(f"Examining key: {key}")
                    
                    # Check if the key contains the entire JSON structure
                    if '`zoom_refresh_token`' in key and '`zoom_client_id`' in key and '`zoom_client_secret`' in key:
                        logger.debug("Found JSON-like structure in key")
                        
                        # Try to extract the JSON values directly
                        refresh_token_match = re.search(r'`zoom_refresh_token`:\s*`([^`]+)`', key)
                        client_id_match = re.search(r'`zoom_client_id`:\s*`([^`]+)`', key)
                        client_secret_match = re.search(r'`zoom_client_secret`:\s*`([^`]+)`', key)
                        
                        if refresh_token_match and client_id_match and client_secret_match:
                            refresh_token = refresh_token_match.group(1)
                            client_id = client_id_match.group(1)
                            client_secret = client_secret_match.group(1)
                            
                            logger.debug(f"Extracted values: refresh_token={refresh_token[:10]}..., client_id={client_id[:5]}...")
                            
                            # Create new arguments dictionary
                            arguments = {
                                "zoom_refresh_token": refresh_token,
                                "zoom_client_id": client_id,
                                "zoom_client_secret": client_secret
                            }
                            
                            logger.debug(f"Using extracted arguments: {json.dumps(arguments)}")
                except Exception as e:
                    logger.error(f"Error extracting values from key: {e}")
            
            if name == "zoom_refresh_token":
                # For refresh token, we need refresh token, client ID and secret
                refresh_token = arguments.get("zoom_refresh_token")
                client_id = arguments.get("zoom_client_id")
                client_secret = arguments.get("zoom_client_secret")
                access_token = arguments.get("zoom_access_token")  # Optional for refresh
                
                logger.debug(f"Refresh token parameters: refresh_token={refresh_token[:10] if refresh_token else None}..., client_id={client_id[:5] if client_id else None}...")
                
                if not refresh_token:
                    raise ValueError("zoom_refresh_token is required for token refresh")
                
                if not client_id or not client_secret:
                    raise ValueError("Both zoom_client_id and zoom_client_secret are required for token refresh")
                
                # Initialize Zoom client for token refresh
                logger.debug("Initializing ZoomClient for token refresh")
                zoom = ZoomClient(
                    access_token=access_token, 
                    refresh_token=refresh_token
                )
                
                # Call the refresh_access_token method with proper error handling
                try:
                    logger.debug("Calling zoom.refresh_access_token")
                    results = zoom.refresh_access_token(client_id=client_id, client_secret=client_secret)
                    logger.debug(f"Results from refresh_access_token: {results[:100]}...")
                    return [types.TextContent(type="text", text=results)]
                except Exception as e:
                    logger.error(f"Exception in refresh_access_token: {str(e)}", exc_info=True)
                    # Print the actual error to help debug
                    return [types.TextContent(type="text", text=json.dumps({
                        "error": str(e),
                        "status": "error"
                    }))]
            
            else:
                # For all other tools, we need access token
                access_token = arguments.get("zoom_access_token")
                
                if not access_token:
                    raise ValueError("zoom_access_token is required")
                
                if name == "zoom_list_recordings":
                    # Initialize Zoom client with just access token
                    logger.debug(f"Initializing Zoom client for list_recordings with access token: {access_token[:10]}...")
                    try:
                        zoom = ZoomClient(
                            access_token=access_token
                        )
                        logger.debug("Zoom client initialized successfully")
                        
                        from_date = arguments.get("from_date")
                        to_date = arguments.get("to_date")
                        page_size = int(arguments.get("page_size", 30))
                        page_number = int(arguments.get("page_number", 1))
                        
                        logger.debug(f"Calling list_recordings with from_date={from_date}, to_date={to_date}, page_size={page_size}, page_number={page_number}")
                        results = zoom.list_recordings(from_date=from_date, to_date=to_date, 
                                                       page_size=page_size, page_number=page_number)
                        logger.debug(f"list_recordings result (first 200 chars): {results[:200]}...")
                        return [types.TextContent(type="text", text=results)]
                    except Exception as e:
                        logger.error(f"Exception in zoom_list_recordings handler: {str(e)}", exc_info=True)
                        return [types.TextContent(type="text", text=f"Error: {str(e)}")]
                    
                elif name == "zoom_get_recording_details":
                    # Initialize Zoom client with just access token
                    zoom = ZoomClient(
                        access_token=access_token
                    )
                    
                    meeting_id = arguments.get("meeting_id")
                    
                    if not meeting_id:
                        raise ValueError("meeting_id is required")
                    
                    results = zoom.get_recording_details(meeting_id=meeting_id)
                    return [types.TextContent(type="text", text=results)]
                    
                elif name == "zoom_get_meeting_transcript":
                    # Initialize Zoom client with just access token
                    zoom = ZoomClient(
                        access_token=access_token
                    )
                    
                    meeting_id = arguments.get("meeting_id")
                    
                    if not meeting_id:
                        raise ValueError("meeting_id is required")
                    
                    results = zoom.get_meeting_transcript(meeting_id=meeting_id)
                    return [types.TextContent(type="text", text=results)]

                else:
                    raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("Server running with stdio transport")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="zoom",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    import asyncio
    
    # No local OAuth parameters needed - all credentials are passed in tool arguments
    asyncio.run(main()) 