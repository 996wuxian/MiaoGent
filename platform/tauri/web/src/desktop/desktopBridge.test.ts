import { describe, expect, it } from 'vitest';
import { createNavigationGate, shouldRefreshDesktopData } from './desktopBridge';

describe('desktop event refresh policy', () => {
  it('refreshes for completed work and conservative attention events', () => {
    expect(shouldRefreshDesktopData({ event: 'startup_summary', payload: {} })).toBe(true);
    expect(shouldRefreshDesktopData({ event: 'sync_summary', payload: {} })).toBe(true);
    expect(shouldRefreshDesktopData({ event: 'important_mail', payload: { uid: 'uid:7' } })).toBe(true);
    expect(shouldRefreshDesktopData({ event: 'mail_processed', payload: { uid: 'uid:8' } })).toBe(true);
    expect(shouldRefreshDesktopData({ event: 'attention_required', payload: { uid: 'uid:9' } })).toBe(true);
    expect(shouldRefreshDesktopData({ event: 'watcher_status', payload: { status: 'idle' } })).toBe(false);
  });
});

describe('desktop navigation gate', () => {
  it('does not deliver a cold-start notification target before the backend is ready', () => {
    const navigated: Array<{ kind: 'summary' } | { kind: 'mail'; uid: string }> = [];
    const gate = createNavigationGate((target) => navigated.push(target));

    expect(gate.deliver({ kind: 'mail', uid: 'uid:7' })).toBe(false);
    expect(navigated).toEqual([]);

    gate.setBackendReady();
    expect(gate.deliver({ kind: 'mail', uid: 'uid:7' })).toBe(true);
    expect(navigated).toEqual([{ kind: 'mail', uid: 'uid:7' }]);

    gate.setBackendUnavailable();
    expect(gate.deliver({ kind: 'summary' })).toBe(false);
    expect(navigated).toHaveLength(1);
    gate.setBackendReady();
    expect(gate.deliver({ kind: 'summary' })).toBe(true);
    expect(navigated[1]).toEqual({ kind: 'summary' });
  });
});
