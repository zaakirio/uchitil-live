// Native macOS permission handling using AVFoundation APIs
//
// On macOS Sequoia (15.x), the cpal-based approach of opening an audio stream
// does NOT reliably trigger the TCC (Transparency, Consent, and Control) permission
// dialog, especially for bare Mach-O executables that aren't proper .app bundles.
//
// The correct approach is to use AVCaptureDevice APIs:
// - authorizationStatusForMediaType: to check current status
// - requestAccessForMediaType:completionHandler: to request access
//
// These APIs are the officially supported way to trigger macOS permission dialogs.

#[cfg(target_os = "macos")]
pub mod native {
    use log::{info, warn};

    /// Check the current microphone authorization status without triggering a prompt.
    /// Returns: "not_determined", "restricted", "denied", or "authorized"
    pub fn check_microphone_permission_status() -> String {
        unsafe {
            use objc::runtime::{Class, Object};
            use objc::{msg_send, sel, sel_impl};

            let cls = match Class::get("AVCaptureDevice") {
                Some(c) => c,
                None => {
                    warn!("[macos_permissions] AVCaptureDevice class not found");
                    return "not_determined".to_string();
                }
            };

            // Create NSString for AVMediaTypeAudio
            // AVMediaTypeAudio is the constant @"soun" (FourCC for sound)
            let ns_string_cls = Class::get("NSString").unwrap();
            let media_type: *mut Object =
                msg_send![ns_string_cls, stringWithUTF8String: b"soun\0".as_ptr()];

            // [AVCaptureDevice authorizationStatusForMediaType:]
            // Returns AVAuthorizationStatus (NSInteger):
            //   0 = notDetermined
            //   1 = restricted
            //   2 = denied
            //   3 = authorized
            let status: i64 = msg_send![cls, authorizationStatusForMediaType: media_type];

            let result = match status {
                0 => "not_determined",
                1 => "restricted",
                2 => "denied",
                3 => "authorized",
                _ => {
                    warn!(
                        "[macos_permissions] Unknown authorization status: {}",
                        status
                    );
                    "not_determined"
                }
            };

            info!(
                "[macos_permissions] Microphone authorization status: {}",
                result
            );
            result.to_string()
        }
    }

    /// Request microphone permission using the native AVCaptureDevice API.
    ///
    /// This calls [AVCaptureDevice requestAccessForMediaType:completionHandler:]
    /// which properly triggers the macOS TCC permission dialog when status is
    /// "not_determined". The dialog is associated with the calling process, so it
    /// works for both .app bundles and bare executables.
    ///
    /// Returns true if permission was granted, false otherwise.
    /// This function blocks until the user responds to the dialog (with a 60s timeout).
    pub fn request_microphone_permission() -> bool {
        use block::ConcreteBlock;
        use objc::runtime::{Class, Object};
        use objc::{msg_send, sel, sel_impl};
        use std::sync::{Arc, Condvar, Mutex};

        info!("[macos_permissions] Requesting microphone permission via AVCaptureDevice...");

        // First check current status
        let status = check_microphone_permission_status();
        match status.as_str() {
            "authorized" => {
                info!("[macos_permissions] Already authorized");
                return true;
            }
            "denied" | "restricted" => {
                info!(
                    "[macos_permissions] Status is '{}' - user must grant in System Settings",
                    status
                );
                return false;
            }
            _ => {
                info!(
                    "[macos_permissions] Status is 'not_determined' - will show permission dialog"
                );
            }
        }

        // Use a condvar to wait for the async completion handler
        let result = Arc::new((Mutex::new(None::<bool>), Condvar::new()));
        let result_clone = Arc::clone(&result);

        unsafe {
            let cls = Class::get("AVCaptureDevice").unwrap();

            // Create NSString for AVMediaTypeAudio ("soun")
            let ns_string_cls = Class::get("NSString").unwrap();
            let media_type: *mut Object =
                msg_send![ns_string_cls, stringWithUTF8String: b"soun\0".as_ptr()];

            // Create the completion block: ^(BOOL granted) { ... }
            // In the objc crate, BOOL maps to Rust bool
            let handler = ConcreteBlock::new(move |granted: bool| {
                info!(
                    "[macos_permissions] Permission dialog callback: granted={}",
                    granted
                );
                let (lock, cvar) = &*result_clone;
                let mut value = lock.lock().unwrap();
                *value = Some(granted);
                cvar.notify_one();
            });
            let handler = handler.copy();

            // [AVCaptureDevice requestAccessForMediaType:completionHandler:]
            let _: () = msg_send![cls, requestAccessForMediaType: media_type
                                       completionHandler: &*handler];
        }

        // Wait for the completion handler with timeout
        let (lock, cvar) = &*result;
        let mut value = lock.lock().unwrap();

        let timeout = std::time::Duration::from_secs(60);
        let start = std::time::Instant::now();

        while value.is_none() {
            let remaining = timeout
                .checked_sub(start.elapsed())
                .unwrap_or(std::time::Duration::ZERO);

            if remaining.is_zero() {
                warn!("[macos_permissions] Timed out waiting for permission dialog response");
                return false;
            }

            let (new_value, timeout_result) = cvar.wait_timeout(value, remaining).unwrap();
            value = new_value;

            if timeout_result.timed_out() && value.is_none() {
                warn!("[macos_permissions] Condvar timed out");
                return false;
            }
        }

        let granted = value.unwrap_or(false);
        info!(
            "[macos_permissions] Final permission result: granted={}",
            granted
        );
        granted
    }
}

#[cfg(not(target_os = "macos"))]
pub mod native {
    /// Non-macOS: always returns "authorized"
    pub fn check_microphone_permission_status() -> String {
        "authorized".to_string()
    }

    /// Non-macOS: always returns true
    pub fn request_microphone_permission() -> bool {
        true
    }
}
