/**
 * Storage Service
 *
 * Handles all session storage and retrieval Tauri backend calls (SQLite persistence).
 * Pure 1-to-1 wrapper - no error handling changes, exact same behavior as direct invoke calls.
 */

import { invoke } from '@tauri-apps/api/core';
import { Transcript } from '@/types';

export interface SaveSessionRequest {
  sessionTitle: string;
  transcripts: Transcript[];
  folderPath: string | null;
}

export interface SaveSessionResponse {
  meeting_id: string;
}

export interface Session {
  id: string;
  title: string;
  [key: string]: any; // Allow additional properties from backend
}

/**
 * Storage Service
 * Singleton service for managing session storage operations
 */
export class StorageService {
  /**
   * Save session transcript to SQLite database
   * @param sessionTitle - Title of the session
   * @param transcripts - Array of transcript segments
   * @param folderPath - Optional folder path for audio file
   * @returns Promise with { meeting_id: string }
   */
  async saveSession(
    sessionTitle: string,
    transcripts: Transcript[],
    folderPath: string | null
  ): Promise<SaveSessionResponse> {
    return invoke<SaveSessionResponse>('api_save_transcript', {
      sessionTitle: sessionTitle,
      transcripts,
      folderPath,
    });
  }

  /**
   * Get session details by ID
   * @param sessionId - ID of the session to fetch
   * @returns Promise with session details
   */
  async getSession(sessionId: string): Promise<Session> {
    return invoke<Session>('api_get_session', { meetingId: sessionId });
  }

  /**
   * Get list of all sessions
   * @returns Promise with array of sessions
   */
  async getSessions(): Promise<Session[]> {
    return invoke<Session[]>('api_get_sessions');
  }
}

// Export singleton instance
export const storageService = new StorageService();
