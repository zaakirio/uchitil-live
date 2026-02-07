import { useState, useCallback, useRef, useEffect } from 'react';
import { Transcript, Summary } from '@/types';
import { BlockNoteSummaryViewRef } from '@/components/AISummary/BlockNoteSummaryView';
import { CurrentSession, useSidebar } from '@/components/Sidebar/SidebarProvider';
import { invoke as invokeTauri } from '@tauri-apps/api/core';
import { toast } from 'sonner';

interface UseSessionDataProps {
  meeting: any;
  summaryData: Summary | null;
  onSessionUpdated?: () => Promise<void>;
}

export function useSessionData({ meeting, summaryData, onSessionUpdated }: UseSessionDataProps) {
  // State
  // Use prop directly since summary generation fetches transcripts independently
  const transcripts = meeting.transcripts;
  const [sessionTitle, setSessionTitle] = useState(meeting.title || '+ New Call');
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [isTitleDirty, setIsTitleDirty] = useState(false);
  const [aiSummary, setAiSummary] = useState<Summary | null>(summaryData);
  const [isSaving, setIsSaving] = useState(false);
  const [, setIsSummaryDirty] = useState(false);
  const [, setError] = useState<string>('');

  // Ref for BlockNoteSummaryView
  const blockNoteSummaryRef = useRef<BlockNoteSummaryViewRef>(null);

  // Sidebar context
  const { setCurrentSession, setSessions, sessions: sidebarSessions } = useSidebar();

  // Sync aiSummary state when summaryData prop changes (fixes display of fetched summaries)
  useEffect(() => {
    console.log('[useSessionData] Syncing summary data from prop:', summaryData ? 'present' : 'null');
    setAiSummary(summaryData);
  }, [summaryData]); // Only trigger when parent prop changes, not when aiSummary changes

  // Handlers
  const handleTitleChange = useCallback((newTitle: string) => {
    setSessionTitle(newTitle);
    setIsTitleDirty(true);
  }, []);

  const handleSummaryChange = useCallback((newSummary: Summary) => {
    setAiSummary(newSummary);
  }, []);

  const handleSaveSessionTitle = useCallback(async () => {
    try {
      await invokeTauri('api_save_session_title', {
        meetingId: meeting.id,
        title: sessionTitle,
      });

      console.log('Save session title success');
      setIsTitleDirty(false);

      // Update sessions with new title
      const updatedSessions = sidebarSessions.map((m: CurrentSession) =>
        m.id === meeting.id ? { id: m.id, title: sessionTitle } : m
      );
      setSessions(updatedSessions);
      setCurrentSession({ id: meeting.id, title: sessionTitle });
      return true;
    } catch (error) {
      console.error('Failed to save session title:', error);
      if (error instanceof Error) {
        setError(error.message);
      } else {
        setError('Failed to save session title: Unknown error');
      }
      return false;
    }
  }, [meeting.id, sessionTitle, sidebarSessions, setSessions, setCurrentSession]);

  const handleSaveSummary = useCallback(async (summary: Summary | { markdown?: string; summary_json?: any[] }) => {
    console.log('📄 handleSaveSummary called with:', {
      hasMarkdown: 'markdown' in summary,
      hasSummaryJson: 'summary_json' in summary,
      summaryKeys: Object.keys(summary)
    });

    try {
      let formattedSummary: any;

      // Check if it's the new BlockNote format
      if ('markdown' in summary || 'summary_json' in summary) {
        console.log('📄 Saving new format (markdown/blocknote)');
        formattedSummary = summary;
      } else {
        console.log('📄 Saving legacy format');
        formattedSummary = {
          SessionName: sessionTitle,
          MeetingName: sessionTitle,
          SessionNotes: {
            sections: Object.entries(summary).map(([, section]) => ({
              title: section.title,
              blocks: section.blocks
            }))
          }
        };
      }

      await invokeTauri('api_save_session_summary', {
        meetingId: meeting.id,
        summary: formattedSummary,
      });

      console.log('✅ Save session summary success');
    } catch (error) {
      console.error('❌ Failed to save session summary:', error);
      if (error instanceof Error) {
        setError(error.message);
      } else {
        setError('Failed to save session summary: Unknown error');
      }
    }
  }, [meeting.id, sessionTitle]);

  const saveAllChanges = useCallback(async () => {
    setIsSaving(true);
    try {
      // Save session title only if changed
      if (isTitleDirty) {
        await handleSaveSessionTitle();
      }

      // Save BlockNote editor changes if dirty
      if (blockNoteSummaryRef.current?.isDirty) {
        console.log('💾 Saving BlockNote editor changes...');
        await blockNoteSummaryRef.current.saveSummary();
      } else if (aiSummary) {
        await handleSaveSummary(aiSummary);
      }

      toast.success("Changes saved successfully");
    } catch (error) {
      console.error('Failed to save changes:', error);
      toast.error("Failed to save changes", { description: String(error) });
    } finally {
      setIsSaving(false);
    }
  }, [isTitleDirty, handleSaveSessionTitle, aiSummary, handleSaveSummary]);

  // Update session title from external source (e.g., AI summary)
  const updateSessionTitle = useCallback((newTitle: string) => {
    console.log('📝 Updating session title to:', newTitle);
    setSessionTitle(newTitle);
    const updatedSessions = sidebarSessions.map((m: CurrentSession) =>
      m.id === meeting.id ? { id: m.id, title: newTitle } : m
    );
    setSessions(updatedSessions);
    setCurrentSession({ id: meeting.id, title: newTitle });
  }, [meeting.id, sidebarSessions, setSessions, setCurrentSession]);

  return {
    // State
    transcripts,
    sessionTitle,
    isEditingTitle,
    isTitleDirty,
    aiSummary,
    isSaving,
    blockNoteSummaryRef,

    // Setters
    setSessionTitle,
    setIsEditingTitle,
    setAiSummary,
    setIsSummaryDirty,

    // Handlers
    handleTitleChange,
    handleSummaryChange,
    handleSaveSummary,
    handleSaveSessionTitle,
    saveAllChanges,
    updateSessionTitle,
  };
}
