/**
 * useTranscriptRecovery Hook
 *
 * Orchestrates transcript recovery operations for interrupted sessions.
 * Provides functionality to detect, preview, and recover sessions from IndexedDB.
 */

import { useState, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { indexedDBService, MeetingMetadata, StoredTranscript } from '@/services/indexedDBService';
import { storageService } from '@/services/storageService';

interface AudioRecoveryStatus {
  status: string; // "success" | "partial" | "failed" | "none"
  chunk_count: number;
  estimated_duration_seconds: number;
  audio_file_path?: string;
  message: string;
}

export interface UseTranscriptRecoveryReturn {
  recoverableSessions: MeetingMetadata[];
  isLoading: boolean;
  isRecovering: boolean;
  checkForRecoverableTranscripts: () => Promise<void>;
  recoverSession: (meetingId: string) => Promise<{ success: boolean; audioRecoveryStatus?: AudioRecoveryStatus | null; meetingId?: string }>;
  loadSessionTranscripts: (meetingId: string) => Promise<StoredTranscript[]>;
  deleteRecoverableSession: (meetingId: string) => Promise<void>;
}

export function useTranscriptRecovery(): UseTranscriptRecoveryReturn {
  const [recoverableSessions, setRecoverableSessions] = useState<MeetingMetadata[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isRecovering, setIsRecovering] = useState(false);

  /**
   * Check for recoverable sessions in IndexedDB
   */
  const checkForRecoverableTranscripts = useCallback(async () => {
    setIsLoading(true);
    try {
      const sessions = await indexedDBService.getAllMeetings();

      // Filter out sessions older than 7 days and newer than 15 seconds
      // The 15 seconds threshold prevents showing sessions from the current session (just in case)
      // where recording just stopped but hasn't been fully saved yet
      const cutoffTime = Date.now() - (7 * 24 * 60 * 60 * 1000);
      const secondsAgo = Date.now() - (15 * 1000);

      const recentSessions = sessions.filter(m => {
        const isWithinRetention = m.lastUpdated > cutoffTime; // Not older than 7 days
        const isOldEnough = m.lastUpdated < secondsAgo; // Older than 15 seconds
        return isWithinRetention && isOldEnough;
      });

      // Verify audio checkpoint availability for each session
      const sessionsWithAudioStatus = await Promise.all(
        recentSessions.map(async (session) => {
          if (session.folderPath) {
            try {
              const hasAudio = await invoke<boolean>('has_audio_checkpoints', {
                meetingFolder: session.folderPath
              });

              // If no audio files, clear folderPath to show "No audio" in UI
              return {
                ...session,
                folderPath: hasAudio ? session.folderPath : undefined
              };
            } catch (error) {
              console.warn('Failed to check audio for session:', error);
              // On error, assume no audio to be safe
              return { ...session, folderPath: undefined };
            }
          }
          return session;
        })
      );


      setRecoverableSessions(sessionsWithAudioStatus);
    } catch (error) {
      console.error('Failed to check for recoverable transcripts:', error);
      setRecoverableSessions([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  /**
   * Load transcripts for preview
   */
  const loadSessionTranscripts = useCallback(async (meetingId: string): Promise<StoredTranscript[]> => {
    try {
      const transcripts = await indexedDBService.getTranscripts(meetingId);
      // Sort by sequence ID
      transcripts.sort((a, b) => (a.sequenceId || 0) - (b.sequenceId || 0));
      return transcripts;
    } catch (error) {
      console.error('Failed to load session transcripts:', error);
      return [];
    }
  }, []);

  /**
   * Recover a session from IndexedDB
   */
  const recoverSession = useCallback(async (meetingId: string): Promise<{ success: boolean; audioRecoveryStatus?: AudioRecoveryStatus | null; meetingId?: string }> => {
    setIsRecovering(true);
    try {
      // 1. Load session metadata
      const metadata = await indexedDBService.getMeetingMetadata(meetingId);
      if (!metadata) {
        throw new Error('Session metadata not found');
      }

      // 2. Load all transcripts
      const transcripts = await loadSessionTranscripts(meetingId);
      if (transcripts.length === 0) {
        throw new Error('No transcripts found for this session');
      }

      // 3. Check for folder path
      let folderPath = metadata.folderPath;


      if (!folderPath) {
        // Try to get from backend (might exist if only app crashed, not system)
        try {
          folderPath = await invoke<string>('get_session_folder_path');
        } catch (error) {
          folderPath = undefined;
        }
      }

      // 4. Attempt audio recovery if folder path exists
      let audioRecoveryStatus: AudioRecoveryStatus | null = null;
      if (folderPath) {
        try {
          audioRecoveryStatus = await invoke<AudioRecoveryStatus>(
            'recover_audio_from_checkpoints',
            { meetingFolder: folderPath, sampleRate: 48000 }
          );
        } catch (error) {
          console.error('Audio recovery failed:', error);
          audioRecoveryStatus = {
            status: 'failed',
            chunk_count: 0,
            estimated_duration_seconds: 0,
            message: error instanceof Error ? error.message : 'Unknown error'
          };
        }
      } else {
        audioRecoveryStatus = {
          status: 'none',
          chunk_count: 0,
          estimated_duration_seconds: 0,
          message: 'No folder path available'
        };
      }

      // 5. Convert StoredTranscripts to the format expected by storageService
      const formattedTranscripts = transcripts.map((t, index) => ({
        id: t.id?.toString() || `${Date.now()}-${index}`,
        text: t.text,
        timestamp: t.timestamp,
        sequence_id: t.sequenceId || index,
        chunk_start_time: (t as any).chunk_start_time,
        is_partial: (t as any).is_partial || false,
        confidence: t.confidence,
        audio_start_time: (t as any).audio_start_time,
        audio_end_time: (t as any).audio_end_time,
        duration: (t as any).duration,
      }));

      // 6. Save to backend database using existing save utilities
      const saveResponse = await storageService.saveSession(
        metadata.title,
        formattedTranscripts,
        folderPath ?? null
      );

      const savedSessionId = saveResponse.meeting_id;

      // 7. Mark as saved in IndexedDB
      await indexedDBService.markMeetingSaved(meetingId);


      // 8. Clean up checkpoint files
      if (folderPath) {
        try {
          await invoke('cleanup_checkpoints', { meetingFolder: folderPath });
        } catch (error) {
          // Non-fatal - don't fail recovery if cleanup fails
          console.warn('Checkpoint cleanup failed (non-fatal):', error);
        }
      }

      // 9. Remove from recoverable list
      setRecoverableSessions(prev => prev.filter(m => m.meetingId !== meetingId));

      return {
        success: true,
        audioRecoveryStatus,
        meetingId: savedSessionId
      };
    } catch (error) {
      console.error('Failed to recover session:', error);
      throw error;
    } finally {
      setIsRecovering(false);
    }
  }, [loadSessionTranscripts]);

  /**
   * Delete a recoverable session
   */
  const deleteRecoverableSession = useCallback(async (meetingId: string): Promise<void> => {
    try {
      await indexedDBService.deleteMeeting(meetingId);
      setRecoverableSessions(prev => prev.filter(m => m.meetingId !== meetingId));
    } catch (error) {
      console.error('Failed to delete session:', error);
      throw error;
    }
  }, []);

  return {
    recoverableSessions,
    isLoading,
    isRecovering,
    checkForRecoverableTranscripts,
    recoverSession,
    loadSessionTranscripts,
    deleteRecoverableSession
  };
}
