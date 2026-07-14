export const PRIVACY_SENSITIVE_ERROR = 'privacy_sensitive';
export const PRIVACY_PRIVATE_ERROR = 'privacy_private';
export type MailPrivacyLevel = 'normal' | 'sensitive' | 'private';

export function isSensitiveMail(value: {
  analysis_error?: string | null;
  privacy_level?: string | null;
  subject?: string | null;
  sender?: string | null;
  summary_zh?: string | null;
  priority_reason?: string | null;
  error?: string | null;
} | null | undefined) {
  return getMailPrivacyLevel(value) !== 'normal';
}

export function getMailPrivacyLevel(value: {
  analysis_error?: string | null;
  privacy_level?: string | null;
  subject?: string | null;
  sender?: string | null;
  summary_zh?: string | null;
  priority_reason?: string | null;
  error?: string | null;
} | null | undefined): MailPrivacyLevel {
  if (!value) return 'normal';
  if (value.privacy_level === 'private') return 'private';
  if (value.privacy_level === 'sensitive') return 'sensitive';
  if (value.privacy_level === 'normal') return 'normal';
  if (value.analysis_error === PRIVACY_PRIVATE_ERROR) return 'private';
  if (value.analysis_error === PRIVACY_SENSITIVE_ERROR) return 'sensitive';
  const scanText = (value.subject ?? '').toLowerCase();
  if (/身份证|护照|银行卡|银行账号|社保|公积金|税务|住址|家庭地址|手机号/.test(scanText)) return 'private';
  if (
    /隐私保护模式|PrivacyProtected/.test(scanText) ||
    /\boffer\b|\boffer\s*letter\b|\bemployment\b/.test(scanText) ||
    /录用|入职|聘用|入职通知|录取通知|薪资|工资|待遇|合同|劳动合同|保密协议/.test(scanText)
  ) {
    return 'sensitive';
  }
  return 'normal';
}
