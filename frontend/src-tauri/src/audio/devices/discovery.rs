use anyhow::{anyhow, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use log::error;

use super::configuration::{AudioDevice, DeviceType};
use super::platform;

/// List all available audio devices on the system
pub async fn list_audio_devices() -> Result<Vec<AudioDevice>> {
    let host = cpal::default_host();

    // Platform-specific device enumeration
    let mut devices = {
        #[cfg(target_os = "windows")]
        {
            platform::configure_windows_audio(&host)?
        }

        #[cfg(target_os = "linux")]
        {
            platform::configure_linux_audio(&host)?
        }

        #[cfg(target_os = "macos")]
        {
            platform::configure_macos_audio(&host)?
        }
    };

    // Add any additional devices from the default host
    if let Ok(other_devices) = host.devices() {
        for device in other_devices {
            if let Ok(name) = device.name() {
                if !devices.iter().any(|d| d.name == name) {
                    devices.push(AudioDevice::new(name, DeviceType::Output));
                }
            }
        }
    }

    Ok(devices)
}

/// Trigger audio permission request on platforms that require it.
///
/// On macOS: Uses the native AVCaptureDevice.requestAccessForMediaType: API which
/// properly triggers the TCC permission dialog. The cpal-based approach does NOT
/// reliably trigger the dialog on macOS Sequoia (15.x), especially for bare executables.
///
/// On other platforms: Falls back to the cpal stream-based approach.
///
/// Returns Ok(true) if permission is granted, Ok(false) if denied, Err if something went wrong
pub fn trigger_audio_permission() -> Result<bool> {
    use log::info;

    // On macOS, use the native AVCaptureDevice API which properly triggers TCC
    #[cfg(target_os = "macos")]
    {
        info!("[trigger_audio_permission] Using native AVCaptureDevice API (macOS)");
        let granted = crate::audio::macos_permissions::native::request_microphone_permission();
        return Ok(granted);
    }

    // On other platforms, use the cpal stream approach
    #[cfg(not(target_os = "macos"))]
    {
        trigger_audio_permission_cpal()
    }
}

/// Check current microphone permission status without triggering a prompt.
/// Returns: "not_determined", "restricted", "denied", or "authorized"
pub fn check_microphone_status() -> String {
    #[cfg(target_os = "macos")]
    {
        crate::audio::macos_permissions::native::check_microphone_permission_status()
    }
    #[cfg(not(target_os = "macos"))]
    {
        // On non-macOS, assume authorized if we can get a default input device
        let host = cpal::default_host();
        if host.default_input_device().is_some() {
            "authorized".to_string()
        } else {
            "denied".to_string()
        }
    }
}

/// Original cpal-based permission trigger (used on non-macOS platforms)
#[cfg(not(target_os = "macos"))]
fn trigger_audio_permission_cpal() -> Result<bool> {
    use log::info;

    let host = cpal::default_host();
    let device = match host.default_input_device() {
        Some(d) => d,
        None => {
            info!("[trigger_audio_permission] No default input device found - permission likely denied");
            return Ok(false);
        }
    };

    let config = match device.default_input_config() {
        Ok(c) => c,
        Err(e) => {
            info!("[trigger_audio_permission] Failed to get input config: {} - permission likely denied", e);
            return Ok(false);
        }
    };

    // Build and start an input stream to trigger the permission request
    let stream = match device.build_input_stream(
        &config.into(),
        |_data: &[f32], _: &cpal::InputCallbackInfo| {
            // Do nothing, we just want to trigger the permission request
        },
        |err| error!("Error in audio stream: {}", err),
        None,
    ) {
        Ok(s) => s,
        Err(e) => {
            info!("[trigger_audio_permission] Failed to build input stream: {} - permission likely denied", e);
            return Ok(false);
        }
    };

    // Start the stream to actually trigger the permission dialog
    if let Err(e) = stream.play() {
        info!("[trigger_audio_permission] Failed to play stream: {} - permission likely denied", e);
        return Ok(false);
    }

    // Sleep briefly to allow the permission dialog to appear
    std::thread::sleep(std::time::Duration::from_millis(500));

    info!("[trigger_audio_permission] Stream played successfully - permission granted");
    drop(stream);

    Ok(true)
}
