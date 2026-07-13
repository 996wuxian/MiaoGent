export const PRIVACY_SENSITIVE_ERROR = 'privacy_sensitive';

export function isSensitiveMail(value: {
  analysis_error?: string | null;
  subject?: string | null;
  sender?: string | null;
  summary_zh?: string | null;
  priority_reason?: string | null;
  error?: string | null;
} | null | undefined) {
  if (!value) return false;
  const scanText = [
    value.sender,
    value.subject,
    value.summary_zh,
    value.priority_reason,
    value.error,
  ].filter(Boolean).join('\n').toLowerCase();
  return (
    value.analysis_error === PRIVACY_SENSITIVE_ERROR ||
    /隐私保护模式|PrivacyProtected/.test(scanText) ||
    /\boffer\b|\boffer\s*letter\b|\bemployment\b/.test(scanText) ||
    /录用|入职|聘用|入职通知|录取通知|薪资|工资|待遇|合同|劳动合同|保密协议|身份证|护照|银行卡|银行账号|社保|公积金|税务|住址|家庭地址|手机号/.test(scanText)
  );
}
