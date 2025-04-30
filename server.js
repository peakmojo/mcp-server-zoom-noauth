#!/usr/bin/env node

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import axios from 'axios';
import { Buffer } from 'buffer';
import { DateTime } from 'luxon';

// Initialize logging
const logLevels = {
  ERROR: 0,
  WARN: 1,
  INFO: 2,
  DEBUG: 3
};

class Logger {
  constructor(name) {
    this.name = name;
    this.logLevel = process.env.LOG_LEVEL ? 
      logLevels[(process.env.LOG_LEVEL || 'INFO').toUpperCase()] : 
      logLevels.INFO;
  }

  log(level, message) {
    if (logLevels[level] <= this.logLevel) {
      const timestamp = new Date().toISOString();
      console.error(`${timestamp} - ${this.name} - ${level} - ${message}`);
    }
  }

  info(message) { this.log('INFO', message); }
  warn(message) { this.log('WARN', message); }
  error(message) { this.log('ERROR', message); }
  debug(message) { this.log('DEBUG', message); }
}

const logger = new Logger('zoom-mcp');

class ZoomClient {
  constructor({ accessToken, refreshToken, clientId, clientSecret } = {}) {
    if (!accessToken && !refreshToken) {
      throw new Error("Either accessToken or refreshToken must be provided");
    }
    
    this.accessToken = accessToken;
    this.refreshToken = refreshToken;
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.baseUrl = "https://api.zoom.us/v2";
  }

  _getHeaders() {
    return {
      "Authorization": `Bearer ${this.accessToken}`,
      "Content-Type": "application/json"
    };
  }

  async _handleTokenRefresh(operation) {
    try {
      return await operation();
    } catch (error) {
      logger.error(`Request error: ${error.message}`);
      if (error.response) {
        const statusCode = error.response.status;
        if (statusCode === 401) {
          return JSON.stringify({
            error: "Unauthorized. Token might be expired. Try refreshing your token.",
            details: error.message
          });
        } else {
          return JSON.stringify({
            error: `Zoom API error: ${statusCode}`,
            details: error.message
          });
        }
      }
      return JSON.stringify({
        error: "Request to Zoom API failed",
        details: error.message
      });
    }
  }

  async refreshAccessToken(clientId, clientSecret) {
    logger.debug(`Starting refreshAccessToken with clientId=${clientId?.slice(0, 5)}...`);
    
    if (!this.refreshToken) {
      return JSON.stringify({
        error: "No refresh token provided",
        status: "error"
      });
    }
      
    try {
      this.clientId = clientId;
      this.clientSecret = clientSecret;
      
      const authHeader = Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
      
      const headers = {
        "Authorization": `Basic ${authHeader}`,
        "Content-Type": "application/x-www-form-urlencoded"
      };
      
      const data = {
        grant_type: "refresh_token",
        refresh_token: this.refreshToken
      };
      
      logger.debug(`Making POST request to Zoom OAuth token endpoint with refreshToken=${this.refreshToken.slice(0, 10)}...`);
      
      const response = await axios.post(
        "https://zoom.us/oauth/token",
        data,
        { headers }
      );
      
      logger.debug(`Received response with status code: ${response.status}`);
      
      if (response.status === 200) {
        const result = response.data;
        logger.debug("Successfully refreshed token");
        this.accessToken = result.access_token;
        this.refreshToken = result.refresh_token || this.refreshToken;
        
        const expiresIn = result.expires_in || 3600;
        const expiry = DateTime.now().plus({ seconds: expiresIn });
        
        return JSON.stringify({
          access_token: this.accessToken,
          refresh_token: this.refreshToken,
          expires_at: expiry.toISO(),
          expires_in: expiresIn,
          status: "success"
        });
      } else {
        logger.error(`Failed to refresh token: ${response.status}, Response: ${response.data}`);
        return JSON.stringify({
          error: `Failed to refresh token. Status code: ${response.status}`,
          details: response.data,
          raw_response: response.data,
          status: "error"
        });
      }
    } catch (error) {
      logger.error(`Exception in refreshAccessToken: ${error.message}`);
      return JSON.stringify({
        error: error.message,
        status: "error"
      });
    }
  }

  async listRecordings({ from_date, to_date, page_size = 30, page_number = 1 } = {}) {
    try {
      const operation = async () => {
        logger.debug(`Fetching recordings with page_size=${page_size}, page_number=${page_number}`);
        
        const params = {
          page_size: Math.min(page_size, 300),
          page_number: page_number
        };
        
        if (from_date) params.from = from_date;
        if (to_date) params.to = to_date;
        
        const response = await axios.get(
          `${this.baseUrl}/users/me/recordings`,
          {
            headers: this._getHeaders(),
            params
          }
        );
        
        if (response.status !== 200) {
          return JSON.stringify({
            error: `Failed to retrieve recordings. Status code: ${response.status}`,
            details: response.data,
            status: "error"
          });
        }
        
        return JSON.stringify(response.data);
      };
      
      return await this._handleTokenRefresh(operation);
    } catch (error) {
      logger.error(`Exception in listRecordings: ${error.message}`);
      return JSON.stringify({ error: error.message });
    }
  }

  async getRecordingDetails(meeting_id) {
    try {
      logger.debug(`Fetching recording details for meeting_id=${meeting_id}`);
      
      const response = await axios.get(
        `${this.baseUrl}/meetings/${meeting_id}/recordings`,
        { headers: this._getHeaders() }
      );
      
      if (response.status !== 200) {
        return JSON.stringify({
          error: `Failed to retrieve recording details. Status code: ${response.status}`,
          details: response.data,
          status: "error"
        });
      }
      
      return JSON.stringify(response.data);
    } catch (error) {
      logger.error(`Exception in getRecordingDetails: ${error.message}`);
      if (error.response?.status === 401) {
        return JSON.stringify({
          error: "Unauthorized. Token might be expired. Please refresh your token.",
          status: "error"
        });
      }
      return JSON.stringify({ error: error.message });
    }
  }

  async getMeetingTranscript(meetingId) {
    try {
      const operation = async () => {
        logger.debug(`Fetching transcript for meetingId=${meetingId}`);
        
        const recordingsResponse = await axios.get(
          `${this.baseUrl}/meetings/${meetingId}/recordings`,
          { headers: this._getHeaders() }
        );
        
        if (recordingsResponse.status !== 200) {
          return JSON.stringify({
            error: `Failed to retrieve recording information. Status code: ${recordingsResponse.status}`,
            details: recordingsResponse.data,
            status: "error"
          });
        }
        
        const recordingsData = recordingsResponse.data;
        
        const transcriptFiles = recordingsData.recording_files?.filter(
          file => file.file_type === "TRANSCRIPT"
        ) || [];
        
        if (!transcriptFiles.length) {
          return JSON.stringify({
            error: "No transcript files found for this meeting",
            status: "error"
          });
        }
        
        const transcripts = [];
        for (const file of transcriptFiles) {
          if (file.download_url) {
            const transcriptResponse = await axios.get(
              file.download_url,
              { headers: this._getHeaders() }
            );
            
            if (transcriptResponse.status === 200) {
              transcripts.push({
                file_id: file.id || "",
                file_name: file.file_name || "",
                recording_start: file.recording_start || "",
                recording_end: file.recording_end || "",
                content: transcriptResponse.data
              });
            }
          }
        }
        
        return JSON.stringify({
          meeting_id: meetingId,
          topic: recordingsData.topic || "",
          meeting_duration: recordingsData.duration || 0,
          transcripts,
          status: "success"
        });
      };
      
      return await this._handleTokenRefresh(operation);
    } catch (error) {
      logger.error(`Exception in getMeetingTranscript: ${error.message}`);
      return JSON.stringify({ error: error.message });
    }
  }
}

async function main() {
  logger.info('Starting Zoom MCP server');
  
  try {
    const server = new McpServer({
      name: 'Zoom MCP',
      version: '0.1.0'
    });

    // Define tools
    server.tool(
      'zoom_refresh_token',
      'Refresh the Zoom OAuth2 access token using the refresh token and client credentials for API access',
      {
        zoom_access_token: z.string().optional().describe('Zoom OAuth2 access token (optional if expired)'),
        zoom_refresh_token: z.string().describe('Zoom OAuth2 refresh token'),
        zoom_client_id: z.string().describe('Zoom OAuth2 client ID for token refresh'),
        zoom_client_secret: z.string().describe('Zoom OAuth2 client secret for token refresh')
      },
      async ({ zoom_access_token, zoom_refresh_token, zoom_client_id, zoom_client_secret }) => {
        try {
          const zoom = new ZoomClient({
            accessToken: zoom_access_token,
            refreshToken: zoom_refresh_token
          });
          
          const result = await zoom.refreshAccessToken(zoom_client_id, zoom_client_secret);
          return {
            content: [{ type: 'text', text: result }]
          };
        } catch (error) {
          return {
            content: [{ type: 'text', text: JSON.stringify({ error: error.message, status: 'error' }) }]
          };
        }
      }
    );

    server.tool(
      'zoom_list_recordings',
      'List Zoom cloud recordings from a user\'s Zoom account with pagination support',
      {
        zoom_access_token: z.string().describe('Zoom OAuth2 access token'),
        from_date: z.string().optional().describe('Start date for Zoom recording search in \'YYYY-MM-DD\' format'),
        to_date: z.string().optional().describe('End date for Zoom recording search in \'YYYY-MM-DD\' format'),
        page_size: z.number().optional().describe('Number of Zoom recordings to return per page (default: 30, max: 300)'),
        page_number: z.number().optional().describe('Page number of Zoom recordings to return (default: 1)')
      },
      async ({ zoom_access_token, from_date, to_date, page_size = 30, page_number = 1 }) => {
        try {
          const zoom = new ZoomClient({ accessToken: zoom_access_token });
          logger.error(`listing recordings with from_date=${from_date}, to_date=${to_date}, page_size=${page_size}, page_number=${page_number}`);
          const result = await zoom.listRecordings({ from_date, to_date, page_size, page_number });
          return {
            content: [{ type: 'text', text: result }]
          };
        } catch (error) {
          return {
            content: [{ type: 'text', text: `Error: ${error.message}` }]
          };
        }
      }
    );

    server.tool(
      'zoom_get_recording_details',
      'Get detailed information about a specific Zoom meeting recording including recording files and metadata',
      {
        zoom_access_token: z.string().describe('Zoom OAuth2 access token'),
        meeting_id: z.string().describe('The Zoom meeting ID to retrieve recording details for')
      },
      async ({ zoom_access_token, meeting_id }) => {
        try {
          const zoom = new ZoomClient({ accessToken: zoom_access_token });
          const result = await zoom.getRecordingDetails(meeting_id);
          return {
            content: [{ type: 'text', text: result }]
          };
        } catch (error) {
          return {
            content: [{ type: 'text', text: `Error: ${error.message}` }]
          };
        }
      }
    );

    server.tool(
      'zoom_get_meeting_transcript',
      'Get transcript files and content from a specific Zoom meeting recording if available',
      {
        zoom_access_token: z.string().describe('Zoom OAuth2 access token'),
        meeting_id: z.string().describe('The Zoom meeting ID to retrieve transcript for')
      },
      async ({ zoom_access_token, meeting_id }) => {
        try {
          const zoom = new ZoomClient({ accessToken: zoom_access_token });
          const result = await zoom.getMeetingTranscript(meeting_id);
          return {
            content: [{ type: 'text', text: result }]
          };
        } catch (error) {
          return {
            content: [{ type: 'text', text: `Error: ${error.message}` }]
          };
        }
      }
    );

    // Use STDIO transport
    const transport = new StdioServerTransport();
    await server.connect(transport);
    
    logger.info('MCP server started and ready to receive requests');
  } catch (error) {
    logger.error(`Error starting server: ${error.message}`);
    process.exit(1);
  }
}

// Start the server
main(); 