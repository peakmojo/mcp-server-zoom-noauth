# MCP Server for Zoom (No Auth)

[![Docker Hub](https://img.shields.io/docker/pulls/buryhuang/mcp-server-zoom-noauth?label=Docker%20Hub)](https://hub.docker.com/r/buryhuang/mcp-server-zoom-noauth) 
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat)](https://opensource.org/licenses/MIT)

This project is a Model Control Protocol (MCP) server for accessing Zoom API functionality without requiring direct authentication from the end user. It handles the OAuth flows and provides a set of tools for interacting with Zoom recordings and transcripts.

## Features

- OAuth credential management through tool arguments (no local auth flow)
- List user's cloud recordings with pagination
- Get detailed information about specific meeting recordings
- Access meeting transcripts

## Installation

1. Clone the repository:
```bash
git clone https://github.com/peakmojo/mcp-server-zoom-noauth.git
cd mcp-server-zoom-noauth
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Docker

### Building the Docker Image

```bash
# Build the Docker image
docker build -t mcp-server-zoom-noauth .
```

### Cross-Platform Publishing

To publish the Docker image for multiple platforms, you can use the docker buildx command:

1. Create a new builder instance (if you haven't already):
```bash
docker buildx create --use
```

2. Build and push the image for multiple platforms:
```bash
docker buildx build --platform linux/amd64,linux/arm64 -t buryhuang/mcp-server-zoom-noauth:latest --push .
```

3. Verify the image is available for the specified platforms:
```bash
docker buildx imagetools inspect buryhuang/mcp-server-zoom-noauth:latest
```

## Usage

### Starting the server

```bash
python -m src.mcp_server_zoom_noauth.server
```

### Available Tools

The server provides the following tools:

1. **zoom_refresh_token** - Refresh an OAuth token using a refresh token
2. **zoom_list_recordings** - Get a list of user's cloud recordings
3. **zoom_get_recording_details** - Get detailed information about a specific meeting recording
4. **zoom_get_meeting_transcript** - Get transcript for a specific meeting recording

### Tool Usage Examples

#### Refreshing a token

```json
{
  "zoom_refresh_token": "your_refresh_token",
  "zoom_client_id": "your_client_id",
  "zoom_client_secret": "your_client_secret"
}
```

#### Listing recordings

```json
{
  "zoom_access_token": "your_access_token",
  "from_date": "2023-01-01",
  "to_date": "2023-01-31",
  "page_size": 30,
  "page_number": 1
}
```

#### Getting recording details

```json
{
  "zoom_access_token": "your_access_token",
  "meeting_id": "meeting_id_here"
}
```

#### Getting meeting transcript

```json
{
  "zoom_access_token": "your_access_token",
  "meeting_id": "meeting_id_here"
}
```

## OAuth Credential Handling

This server is designed to be completely "noauth" from its perspective:
- No local authentication flow is needed
- No credentials are stored on the server
- All credentials are passed through tool arguments
- The server can run in a headless environment

To use the tools, you'll need to obtain OAuth credentials from Zoom:
1. Create a Zoom OAuth app in the Zoom Marketplace
2. Configure the required scopes for recordings access
3. Obtain access and refresh tokens through the OAuth flow
4. Pass these tokens as arguments when calling the tools

## Zoom API Reference

This project uses the Zoom API v2. For more information, refer to the [Zoom API documentation](https://developers.zoom.us/docs/api/).

## License

[Apache 2.0](LICENSE) 