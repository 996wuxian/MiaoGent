import { useCallback, useRef, useState } from 'react';

export function useExclusiveAction() {
  const activeRef = useRef(new Set<string>());
  const [active, setActive] = useState<Set<string>>(() => new Set());

  const runExclusive = useCallback(async <T,>(key: string, task: () => Promise<T>): Promise<T | undefined> => {
    if (activeRef.current.has(key)) return undefined;
    activeRef.current.add(key);
    setActive(new Set(activeRef.current));
    try {
      return await task();
    } finally {
      activeRef.current.delete(key);
      setActive(new Set(activeRef.current));
    }
  }, []);

  const isPending = useCallback((key: string) => active.has(key), [active]);

  return { runExclusive, isPending };
}
