'use client';

import { useCallback, useState } from 'react';
import { useDataChannel } from '@livekit/components-react';
import { RECAP_TOPIC, type Recap, parseRecap } from '@/lib/recap';

/**
 * Listens for the agent's recap on the `bakar.recap` topic.
 *
 * Everything here is best-effort: if the packet never arrives, the session ends
 * exactly as it did before this feature existed.
 */
export function useRecap() {
  const [recap, setRecap] = useState<Recap | null>(null);

  const handleMessage = useCallback((message: { payload: Uint8Array }) => {
    const text = new TextDecoder().decode(message.payload);
    const parsed = parseRecap(text);
    if (parsed) setRecap(parsed);
  }, []);

  useDataChannel(RECAP_TOPIC, handleMessage);

  const dismiss = useCallback(() => setRecap(null), []);

  return { recap, dismiss };
}
