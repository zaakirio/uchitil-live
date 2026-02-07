import React, { useEffect, useState, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Mic, Volume2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { OnboardingContainer } from '../OnboardingContainer';
import { PermissionRow } from '../shared';
import { useOnboarding } from '@/contexts/OnboardingContext';

export function PermissionsStep() {
  const { setPermissionStatus, setPermissionsSkipped, permissions, completeOnboarding } = useOnboarding();
  const [isPending, setIsPending] = useState(false);
  const [micStatusDetail, setMicStatusDetail] = useState<string>('');

  // Check actual microphone permission status from the OS
  const checkMicPermissionStatus = useCallback(async () => {
    try {
      const status = await invoke<string>('check_microphone_permission_status');
      console.log('[PermissionsStep] Native mic permission status:', status);
      setMicStatusDetail(status);

      if (status === 'authorized') {
        setPermissionStatus('microphone', 'authorized');
      } else if (status === 'denied' || status === 'restricted') {
        setPermissionStatus('microphone', 'denied');
      }
      // For 'not_determined', leave as whatever the current state is
    } catch (err) {
      console.error('[PermissionsStep] Failed to check mic permission status:', err);
    }
  }, [setPermissionStatus]);

  // Check permissions on mount
  useEffect(() => {
    checkMicPermissionStatus();
  }, [checkMicPermissionStatus]);

  // Request microphone permission using native AVCaptureDevice API
  const handleMicrophoneAction = async () => {
    setIsPending(true);
    try {
      console.log('[PermissionsStep] Requesting microphone permission via native API...');
      // This now uses AVCaptureDevice.requestAccessForMediaType: on macOS
      // which properly triggers the TCC permission dialog
      const granted = await invoke<boolean>('trigger_microphone_permission');
      console.log('[PermissionsStep] Microphone permission result:', granted);

      if (granted) {
        setPermissionStatus('microphone', 'authorized');
        setMicStatusDetail('authorized');
      } else {
        // Check actual status - might be denied or user dismissed
        const status = await invoke<string>('check_microphone_permission_status');
        setMicStatusDetail(status);

        if (status === 'denied' || status === 'restricted') {
          setPermissionStatus('microphone', 'denied');
          // Permission was explicitly denied - need to open System Settings
          try {
            await invoke('open_system_settings', { preferencePane: 'Privacy_Microphone' });
          } catch {
            alert(
              'Please enable microphone access in System Settings → Privacy & Security → Microphone.\n\n' +
              'If Uchitil Live is not listed, try clicking "Enable" again to trigger the permission prompt.'
            );
          }
        } else {
          // Still not_determined - dialog may not have appeared
          setPermissionStatus('microphone', 'denied');
          alert(
            'The permission dialog may not have appeared.\n\n' +
            'Please go to System Settings → Privacy & Security → Microphone\n' +
            'and add Uchitil Live manually, or try recording to trigger the prompt.'
          );
        }
      }
    } catch (err) {
      console.error('[PermissionsStep] Failed to request microphone permission:', err);
      setPermissionStatus('microphone', 'denied');
      try {
        await invoke('open_system_settings', { preferencePane: 'Privacy_Microphone' });
      } catch {
        alert('Please enable microphone access in System Settings → Privacy & Security → Microphone');
      }
    } finally {
      setIsPending(false);
    }
  };

  // Request system audio permission  
  const handleSystemAudioAction = async () => {
    setIsPending(true);
    try {
      console.log('[PermissionsStep] Triggering Audio Capture permission...');
      const granted = await invoke<boolean>('trigger_system_audio_permission_command');
      console.log('[PermissionsStep] System audio permission result:', granted);

      if (granted) {
        setPermissionStatus('systemAudio', 'authorized');
        console.log('[PermissionsStep] Audio Capture permission verified');
      } else {
        setPermissionStatus('systemAudio', 'denied');
        console.log('[PermissionsStep] Audio Capture — opening System Settings');
        try {
          await invoke('open_system_settings', { preferencePane: 'Privacy_ScreenCapture' });
        } catch {
          alert(
            'Please enable Screen & System Audio Recording in System Settings → Privacy & Security → Screen & System Audio Recording.\n\n' +
            'Click the + button and navigate to the Uchitil Live app.'
          );
        }
      }
    } catch (err) {
      console.error('[PermissionsStep] Failed to request system audio permission:', err);
      setPermissionStatus('systemAudio', 'denied');
      try {
        await invoke('open_system_settings', { preferencePane: 'Privacy_ScreenCapture' });
      } catch {
        alert('Please enable Screen Recording in System Settings → Privacy & Security → Screen Recording');
      }
    } finally {
      setIsPending(false);
    }
  };

  // Re-check permissions (useful after returning from System Settings)
  const handleRefreshStatus = async () => {
    console.log('[PermissionsStep] Refreshing permission status...');
    await checkMicPermissionStatus();
  };

  const handleFinish = async () => {
    try {
      await completeOnboarding();
      window.location.reload();
    } catch (error) {
      console.error('Failed to complete onboarding:', error);
    }
  };

  const handleSkip = async () => {
    setPermissionsSkipped(true);
    await handleFinish();
  };

  const allPermissionsGranted =
    permissions.microphone === 'authorized' &&
    permissions.systemAudio === 'authorized';

  return (
    <OnboardingContainer
      title="Grant Permissions"
      description="Uchitil Live needs access to your microphone and system audio to record tutoring sessions"
      step={4}
      hideProgress={true}
      showNavigation={allPermissionsGranted}
      canGoNext={allPermissionsGranted}
    >
      <div className="max-w-lg mx-auto space-y-6">
        {/* Permission Rows */}
        <div className="space-y-4">
          {/* Microphone */}
          <PermissionRow
            icon={<Mic className="w-5 h-5" />}
            title="Microphone"
            description={
              micStatusDetail === 'denied'
                ? 'Denied — please enable in System Settings'
                : micStatusDetail === 'authorized'
                ? 'Access granted'
                : 'Required to capture your voice during sessions'
            }
            status={permissions.microphone}
            isPending={isPending}
            onAction={handleMicrophoneAction}
          />

          {/* System Audio */}
          <PermissionRow
            icon={<Volume2 className="w-5 h-5" />}
            title="System Audio"
            description="Required to capture your tutor's audio"
            status={permissions.systemAudio}
            isPending={isPending}
            onAction={handleSystemAudioAction}
          />
        </div>

        {/* Refresh + Action Buttons */}
        <div className="flex flex-col gap-3 pt-4">
          {/* Refresh button - useful after granting in System Settings */}
          {!allPermissionsGranted && (
            <Button
              variant="outline"
              onClick={handleRefreshStatus}
              className="w-full h-9 text-sm"
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              Re-check Permissions
            </Button>
          )}

          <Button onClick={handleFinish} className="w-full h-11">
            {allPermissionsGranted ? 'Finish Setup' : 'Continue Anyway'}
          </Button>

          {!allPermissionsGranted && (
            <p className="text-xs text-center text-muted-foreground">
              Permissions can also be granted later. When you first try to record, macOS will prompt you.
              <br />
              If you granted permission in System Settings, click "Re-check Permissions" above.
            </p>
          )}
        </div>
      </div>
    </OnboardingContainer>
  );
}
