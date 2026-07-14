use serde_json::Value;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, Runtime};

use super::NavigationTarget;

#[derive(Clone, Debug, PartialEq, Eq)]
struct NotificationContent {
    title: String,
    body: String,
    target: NavigationTarget,
    acknowledgement: DeliveryAcknowledgement,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum DeliveryAcknowledgement {
    StartupSummary(String),
    ImportantMail(String),
}

#[derive(Default)]
pub struct NotificationState(Mutex<Vec<String>>);

impl NotificationState {
    fn defer_startup_mail(&self, mail_key: String) {
        if let Ok(mut pending) = self.0.lock() {
            if !pending.contains(&mail_key) {
                pending.push(mail_key);
            }
        }
    }

    fn take_startup_mail(&self) -> Vec<String> {
        self.0
            .lock()
            .map(|mut pending| std::mem::take(&mut *pending))
            .unwrap_or_default()
    }
}

fn number(payload: &Value, field: &str) -> u64 {
    payload.get(field).and_then(Value::as_u64).unwrap_or(0)
}

fn compact_text(value: &str, max_chars: usize) -> String {
    let compact = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if compact.chars().count() <= max_chars {
        return compact;
    }
    let mut result = compact.chars().take(max_chars).collect::<String>();
    result.push('…');
    result
}

fn text(payload: &Value, field: &str, fallback: &str, max_chars: usize) -> String {
    payload
        .get(field)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(|value| compact_text(value, max_chars))
        .unwrap_or_else(|| fallback.to_string())
}

fn payload_identifier(payload: &Value, field: &str) -> Option<String> {
    match payload.get(field)? {
        Value::String(value) => {
            let value = value.trim();
            (!value.is_empty()).then(|| value.to_string())
        }
        Value::Number(value) => value.as_u64().map(|value| value.to_string()),
        _ => None,
    }
}

fn content_for(event: &str, payload: &Value) -> Option<NotificationContent> {
    if event == "startup_summary" {
        let id = payload_identifier(payload, "id")?;
        return Some(NotificationContent {
            title: "邮件启动整理完成".to_string(),
            body: format!(
                "新增 {} 封 · 待回复 {} 封 · 重要 {} 封 · 紧急 {} 封",
                number(payload, "new_count"),
                number(payload, "reply_count"),
                number(payload, "important_count"),
                number(payload, "urgent_count")
            ),
            target: NavigationTarget::Summary,
            acknowledgement: DeliveryAcknowledgement::StartupSummary(id),
        });
    }

    if event != "important_mail"
        || payload.get("analysis_failed").and_then(Value::as_bool) == Some(true)
        || payload.get("is_seen").and_then(Value::as_bool) == Some(true)
    {
        return None;
    }
    let importance = payload.get("importance").and_then(Value::as_str)?;
    if importance != "important" && importance != "urgent" {
        return None;
    }
    let uid = payload.get("uid").and_then(Value::as_str)?.trim();
    let mail_key = payload.get("mail_key").and_then(Value::as_str)?.trim();
    if uid.is_empty() || mail_key.is_empty() {
        return None;
    }
    let sender = text(payload, "sender", "未知发件人", 80);
    let subject = text(payload, "subject", "(无主题)", 100);
    let reason = payload
        .get("priority_reason")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .or_else(|| payload.get("summary_zh").and_then(Value::as_str))
        .map(|value| compact_text(value, 140))
        .unwrap_or_default();
    let body = if reason.is_empty() {
        format!("{sender} · {subject}")
    } else {
        format!("{sender} · {subject}\n{reason}")
    };
    Some(NotificationContent {
        title: if importance == "urgent" {
            "紧急邮件".to_string()
        } else {
            "重要邮件".to_string()
        },
        body,
        target: NavigationTarget::Mail {
            uid: uid.to_string(),
        },
        acknowledgement: DeliveryAcknowledgement::ImportantMail(mail_key.to_string()),
    })
}

fn summary_notification_is_redundant<R: Runtime>(
    app: &AppHandle<R>,
    target: &NavigationTarget,
) -> bool {
    if !matches!(target, NavigationTarget::Summary) {
        return false;
    }
    app.get_webview_window("main")
        .and_then(|window| window.is_visible().ok())
        .unwrap_or(false)
}

fn is_startup_mail(payload: &Value) -> bool {
    ["trigger", "source"].iter().any(|field| {
        payload
            .get(field)
            .and_then(Value::as_str)
            .is_some_and(|value| value == "startup")
    })
}

fn acknowledge_deferred_startup_mail<R: Runtime>(app: &AppHandle<R>, status: &'static str) {
    for mail_key in app.state::<NotificationState>().take_startup_mail() {
        super::sidecar::acknowledge_notification(app, mail_key, status);
    }
}

#[cfg(windows)]
fn show<R: Runtime>(app: &AppHandle<R>, content: NotificationContent) -> Result<(), String> {
    use notify_rust::{Notification, NotificationResponse};

    let mut notification = Notification::new();
    notification
        .appname("MiaoGent")
        .summary(&content.title)
        .body(&content.body);
    if !cfg!(debug_assertions) {
        notification.app_id(&app.config().identifier);
    }
    let handle = notification
        .show()
        .map_err(|error| format!("Windows toast failed: {error}"))?;
    let app_for_click = app.clone();
    let target = content.target;
    std::thread::spawn(move || {
        let _ = handle.wait_for_response(|response: &NotificationResponse| {
            if matches!(
                response,
                NotificationResponse::Default | NotificationResponse::Action(_)
            ) {
                let _ = super::navigate_main_window(&app_for_click, target.clone());
            }
        });
    });
    Ok(())
}

#[cfg(not(windows))]
fn show<R: Runtime>(_app: &AppHandle<R>, _content: NotificationContent) -> Result<(), String> {
    Err("native notification is only supported on Windows".to_string())
}

pub fn handle_sidecar_event<R: Runtime>(app: &AppHandle<R>, event: &str, payload: &Value) {
    let Some(content) = content_for(event, payload) else {
        return;
    };
    if is_startup_mail(payload) {
        if let DeliveryAcknowledgement::ImportantMail(mail_key) = &content.acknowledgement {
            app.state::<NotificationState>()
                .defer_startup_mail(mail_key.clone());
            return;
        }
    }
    if summary_notification_is_redundant(app, &content.target) {
        if let DeliveryAcknowledgement::StartupSummary(id) = content.acknowledgement {
            super::sidecar::acknowledge_startup_summary(app, id);
        }
        acknowledge_deferred_startup_mail(app, "notified");
        let _ = super::navigate_main_window(app, NavigationTarget::Summary);
        return;
    }
    let acknowledgement = content.acknowledgement.clone();
    match show(app, content) {
        Ok(()) => match acknowledgement {
            DeliveryAcknowledgement::StartupSummary(id) => {
                super::sidecar::acknowledge_startup_summary(app, id);
                acknowledge_deferred_startup_mail(app, "notified");
            }
            DeliveryAcknowledgement::ImportantMail(mail_key) => {
                super::sidecar::acknowledge_notification(app, mail_key, "notified");
            }
        },
        Err(_) => {
            match acknowledgement {
                DeliveryAcknowledgement::StartupSummary(_) => {
                    acknowledge_deferred_startup_mail(app, "failed");
                }
                DeliveryAcknowledgement::ImportantMail(mail_key) => {
                    super::sidecar::acknowledge_notification(app, mail_key, "failed");
                }
            }
            let _ = app.emit(
                "qq-mail-event",
                serde_json::json!({
                    "event": "watcher_status",
                    "payload": { "status": "notification_failed" }
                }),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_safe_startup_summary() {
        let content = content_for(
            "startup_summary",
            &serde_json::json!({
                "new_count": 8,
                "reply_count": 2,
                "important_count": 1,
                "urgent_count": 1,
                "id": 123,
                "items": [{"body": "must not be exposed"}]
            }),
        )
        .unwrap();
        assert_eq!(content.title, "邮件启动整理完成");
        assert_eq!(
            content.body,
            "新增 8 封 · 待回复 2 封 · 重要 1 封 · 紧急 1 封"
        );
        assert!(!content.body.contains("must not be exposed"));
        assert_eq!(content.target, NavigationTarget::Summary);
        assert_eq!(
            content.acknowledgement,
            DeliveryAcknowledgement::StartupSummary("123".to_string())
        );
        assert!(content_for("sync_summary", &serde_json::json!({"new_count": 0})).is_none());
    }

    #[test]
    fn accepts_string_summary_identifier_for_compatibility() {
        let content =
            content_for("startup_summary", &serde_json::json!({"id": " summary-1 "})).unwrap();
        assert_eq!(
            content.acknowledgement,
            DeliveryAcknowledgement::StartupSummary("summary-1".to_string())
        );
        assert!(content_for("startup_summary", &serde_json::json!({"id": -1})).is_none());
    }

    #[test]
    fn only_important_or_urgent_mail_produces_a_mail_notification() {
        let urgent = content_for(
            "important_mail",
            &serde_json::json!({
                "uid": "uid:7",
                "mail_key": "INBOX\u{1f}77\u{1f}uid:7",
                "importance": "urgent",
                "sender": "customer@example.com",
                "subject": "今晚前确认",
                "priority_reason": "存在明确截止时间"
            }),
        )
        .unwrap();
        assert_eq!(urgent.title, "紧急邮件");
        assert_eq!(
            urgent.target,
            NavigationTarget::Mail {
                uid: "uid:7".to_string()
            }
        );

        assert!(content_for(
            "mail_processed",
            &serde_json::json!({"uid": "uid:8", "importance": "general"})
        )
        .is_none());
        assert!(content_for("attention_required", &serde_json::json!({"uid": "uid:9"})).is_none());
        assert!(content_for(
            "important_mail",
            &serde_json::json!({
                "uid": "uid:10",
                "mail_key": "INBOX\u{1f}77\u{1f}uid:10",
                "importance": "important",
                "analysis_failed": true
            })
        )
        .is_none());
        assert!(content_for(
            "important_mail",
            &serde_json::json!({
                "uid": "uid:11",
                "mail_key": "INBOX\u{1f}77\u{1f}uid:11",
                "importance": "important",
                "is_seen": true
            })
        )
        .is_none());
    }

    #[test]
    fn deferred_startup_mail_is_deduplicated_until_summary_delivery() {
        let state = NotificationState::default();
        state.defer_startup_mail("mail-1".to_string());
        state.defer_startup_mail("mail-1".to_string());
        state.defer_startup_mail("mail-2".to_string());
        assert_eq!(state.take_startup_mail(), vec!["mail-1", "mail-2"]);
        assert!(state.take_startup_mail().is_empty());
    }
}
