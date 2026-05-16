// SecondBrain Tauri shell.
//
// Responsibilities:
//   1. Open the main timeline window on launch.
//   2. Register a global ⌘+Space (Cmd+Space) shortcut to summon the
//      transparent search overlay.
//   3. Run a menubar tray with status + quick actions.
//
// All persistence + business logic lives in the Python daemon's HTTP gateway
// at http://127.0.0.1:7821. This file owns no SecondBrain state.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{TrayIcon, TrayIconBuilder},
    webview::WebviewWindowBuilder,
    Emitter, Manager, WebviewUrl,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

const SEARCH_LABEL: &str = "search";
const MAIN_LABEL: &str = "main";
const GATEWAY_BASE: &str = "http://127.0.0.1:7821";

#[derive(Clone, Default)]
struct DaemonState {
    paused: Arc<AtomicBool>,
    running: Arc<AtomicBool>,
}

fn post_daemon_action(action: &str) -> Result<(), String> {
    let body = serde_json::json!({ "action": action });
    let resp = ureq::post(&format!("{GATEWAY_BASE}/daemon"))
        .set("Content-Type", "application/json")
        .send_json(body)
        .map_err(|e| format!("daemon control POST failed: {e}"))?;
    if resp.status() / 100 != 2 {
        return Err(format!("daemon control returned status {}", resp.status()));
    }
    Ok(())
}

#[derive(Debug, serde::Deserialize)]
struct StatusBody {
    running: bool,
    metrics: Option<StatusMetrics>,
}

#[derive(Debug, serde::Deserialize)]
struct StatusMetrics {
    persisted: Option<u64>,
    paused: Option<bool>,
}

fn fetch_status() -> Option<StatusBody> {
    ureq::get(&format!("{GATEWAY_BASE}/status"))
        .timeout(std::time::Duration::from_millis(800))
        .call()
        .ok()
        .and_then(|r| r.into_json::<StatusBody>().ok())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    // Cmd+Space on macOS opens the search overlay.
                    if event.state == ShortcutState::Pressed
                        && shortcut.matches(Modifiers::SUPER, Code::Space)
                    {
                        toggle_search_window(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            // Register the global shortcut.
            let cmd_space = Shortcut::new(Some(Modifiers::SUPER), Code::Space);
            if let Err(e) = app.global_shortcut().register(cmd_space) {
                eprintln!("could not register Cmd+Space: {e}");
            }

            // Honor SB_DEFAULT_TAB so the screenshot pipeline can pre-select
            // any tab deterministically. We schedule a delayed eval; main.ts
            // also polls for the global as a fallback for race conditions.
            let env_tab = std::env::var("SB_DEFAULT_TAB").unwrap_or_default();
            let env_query = std::env::var("SB_DEFAULT_QUERY").unwrap_or_default();
            let env_person = std::env::var("SB_DEFAULT_PERSON").unwrap_or_default();

            let alphanum = |s: &str| -> String {
                s.chars().filter(|c| c.is_ascii_alphanumeric()).collect()
            };
            let safe_js = |s: &str| -> String {
                s.chars()
                    .filter(|c| c.is_ascii_alphanumeric() || *c == ' ' || *c == '-' || *c == '_')
                    .collect()
            };

            let tab = alphanum(&env_tab);
            let query = safe_js(&env_query);
            let person = safe_js(&env_person);

            if !tab.is_empty() || !query.is_empty() || !person.is_empty() {
                if let Some(w) = app.get_webview_window(MAIN_LABEL) {
                    let wc = w.clone();
                    std::thread::spawn(move || {
                        // Park first globals very early (so main.ts reads
                        // them at boot), then re-apply once via the hook
                        // functions after main.ts is up. The double-shot
                        // covers both startup ordering AND the case where
                        // main.ts is already done by the time we fire.
                        let mut early = String::new();
                        if !tab.is_empty() {
                            early.push_str(&format!("window.__SB_DEFAULT_TAB__='{}';", tab));
                        }
                        if !query.is_empty() {
                            early.push_str(&format!("window.__SB_DEFAULT_QUERY__='{}';", query));
                        }
                        if !person.is_empty() {
                            early.push_str(&format!("window.__SB_DEFAULT_PERSON__='{}';", person));
                        }
                        let _ = wc.eval(&early);

                        // Give main.ts ~1s to boot, then nudge the hooks.
                        std::thread::sleep(std::time::Duration::from_millis(1500));
                        let mut late = String::new();
                        if !tab.is_empty() {
                            late.push_str(&format!(
                                "if(window.__sb_apply_tab__)window.__sb_apply_tab__('{}');",
                                tab
                            ));
                        }
                        if !query.is_empty() {
                            late.push_str(&format!(
                                "if(window.__sb_apply_query__)window.__sb_apply_query__('{}');",
                                query
                            ));
                        }
                        if !person.is_empty() {
                            late.push_str(&format!(
                                "if(window.__sb_apply_person__)window.__sb_apply_person__('{}');",
                                person
                            ));
                        }
                        let _ = wc.eval(&late);
                    });
                }
            }

            // Menubar tray.
            let state = DaemonState::default();
            app.manage(state.clone());

            let status_item =
                MenuItem::with_id(app, "status", "Capturing · —", false, None::<&str>)?;
            let pause_item =
                MenuItem::with_id(app, "pause", "Pause Capture", true, None::<&str>)?;
            let open_timeline =
                MenuItem::with_id(app, "open-timeline", "Open Timeline", true, None::<&str>)?;
            let open_search =
                MenuItem::with_id(app, "open-search", "Open Search…", true, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit SecondBrain", true, None::<&str>)?;

            let menu = Menu::with_items(
                app,
                &[
                    &status_item,
                    &separator,
                    &pause_item,
                    &open_timeline,
                    &open_search,
                    &separator,
                    &quit,
                ],
            )?;

            let pause_for_handler = pause_item.clone();
            let status_for_handler = status_item.clone();
            let state_for_handler = state.clone();
            let tray = TrayIconBuilder::with_id("sb-tray")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .icon(app.default_window_icon().unwrap().clone())
                .icon_as_template(true)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "pause" => {
                        let currently_paused = state_for_handler.paused.load(Ordering::Relaxed);
                        let action = if currently_paused { "resume" } else { "pause" };
                        match post_daemon_action(action) {
                            Ok(()) => {
                                let now_paused = !currently_paused;
                                state_for_handler.paused.store(now_paused, Ordering::Relaxed);
                                let _ = pause_for_handler.set_text(if now_paused {
                                    "Resume Capture"
                                } else {
                                    "Pause Capture"
                                });
                                let _ = status_for_handler.set_text(if now_paused {
                                    "Paused"
                                } else {
                                    "Capturing"
                                });
                                let _ = app.emit(
                                    "daemon-control",
                                    serde_json::json!({
                                        "ok": true,
                                        "state": if now_paused { "paused" } else { "running" },
                                    }),
                                );
                            }
                            Err(e) => {
                                eprintln!("tray pause toggle: {e}");
                                // Surface in the webview as a toast.
                                let _ = app.emit(
                                    "daemon-control-error",
                                    serde_json::json!({ "error": e }),
                                );
                            }
                        }
                    }
                    "open-timeline" => {
                        if let Some(w) = app.get_webview_window(MAIN_LABEL) {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "open-search" => toggle_search_window(app),
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            // Poll the gateway every 5s and reflect status in the tray menu.
            spawn_status_poller(app.handle().clone(), state, status_item, pause_item, tray);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Background poller — keeps the tray menu in sync with /status.
fn spawn_status_poller(
    app: tauri::AppHandle<tauri::Wry>,
    state: DaemonState,
    status_item: tauri::menu::MenuItem<tauri::Wry>,
    pause_item: tauri::menu::MenuItem<tauri::Wry>,
    _tray: TrayIcon<tauri::Wry>,
) {
    std::thread::spawn(move || {
        let mut consecutive_failures: u32 = 0;
        loop {
            match fetch_status() {
                Some(s) if s.running => {
                    consecutive_failures = 0;
                    state.running.store(true, Ordering::Relaxed);
                    let paused = s.metrics.as_ref().and_then(|m| m.paused).unwrap_or(false);
                    state.paused.store(paused, Ordering::Relaxed);
                    let persisted = s.metrics.as_ref().and_then(|m| m.persisted).unwrap_or(0);
                    let label = if paused {
                        format!("Paused · {persisted} today")
                    } else {
                        format!("Capturing · {persisted} today")
                    };
                    let _ = status_item.set_text(&label);
                    let _ = pause_item.set_text(if paused {
                        "Resume Capture"
                    } else {
                        "Pause Capture"
                    });
                }
                _ => {
                    consecutive_failures += 1;
                    state.running.store(false, Ordering::Relaxed);
                    let _ = status_item.set_text("Daemon offline");
                    // Toast once after 3 consecutive misses (~15s) so transient
                    // hiccups don't spam the user.
                    if consecutive_failures == 3 {
                        let _ = app.emit(
                            "gateway-unreachable",
                            serde_json::json!({
                                "url": GATEWAY_BASE,
                                "consecutive_misses": consecutive_failures,
                            }),
                        );
                    }
                }
            }
            std::thread::sleep(std::time::Duration::from_secs(5));
        }
    });
}

/// Show + focus the search overlay, creating it lazily.
fn toggle_search_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(win) = app.get_webview_window(SEARCH_LABEL) {
        // Toggle visibility.
        match win.is_visible() {
            Ok(true) => {
                let _ = win.hide();
            }
            _ => {
                let _ = win.show();
                let _ = win.set_focus();
            }
        }
        return;
    }
    // Tauri 2's stable `WebviewWindowBuilder` doesn't expose `transparent`
    // (that requires the `unstable` cargo feature). We get the same visual
    // effect via the CSS backdrop-filter on `body` in `search.html` plus the
    // borderless window + always-on-top. This means the window has a 1px
    // visible boundary instead of a true transparent edge, which is a
    // reasonable trade for shipping on stable Tauri.
    let _ = WebviewWindowBuilder::new(
        app,
        SEARCH_LABEL,
        WebviewUrl::App("search.html".into()),
    )
    .title("SecondBrain · Search")
    .inner_size(600.0, 500.0)
    .decorations(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .resizable(false)
    .center()
    .build();
}
