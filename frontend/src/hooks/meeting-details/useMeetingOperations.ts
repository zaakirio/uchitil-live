import { useCallback } from 'react';
import { invoke as invokeTauri } from '@tauri-apps/api/core';
import { toast } from 'sonner';

interface UseSessionOperationsProps {
  meeting: any;
}

export function useSessionOperations({
  meeting,
}: UseSessionOperationsProps) {

  // Open session folder in file explorer
  const handleOpenSessionFolder = useCallback(async () => {
    try {
      await invokeTauri('open_session_folder', { meetingId: meeting.id });
    } catch (error) {
      console.error('Failed to open session folder:', error);
      toast.error(error as string || 'Failed to open recording folder');
    }
  }, [meeting.id]);

  return {
    handleOpenSessionFolder,
  };
}
