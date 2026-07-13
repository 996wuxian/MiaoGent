export const PRIVACY_SENSITIVE_ERROR = 'privacy_sensitive';

export function isSensitiveMail(value: {
  analysis_error?: string | null;
  summary_zh?: string | null;
  priority_reason?: string | null;
  error?: string | null;
} | null | undefined) {
  if (!value) return false;
  return (
    value.analysis_error === PRIVACY_SENSITIVE_ERROR ||
    /隐私保护模式|PrivacyProtected/.test(value.summary_zh ?? '') ||
    /隐私保护模式|PrivacyProtected/.test(value.priority_reason ?? '') ||
    /隐私保护模式|PrivacyProtected/.test(value.error ?? '')
  );
}
