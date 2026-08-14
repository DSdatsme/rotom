import { useEffect, useRef } from "react";

/**
 * Runs `callback` every `delayMs` milliseconds; pass `null` to pause.
 * The interval only restarts when `delayMs` changes — it always invokes the
 * latest `callback` without needing it in the dependency array.
 */
export function useInterval(callback: () => void, delayMs: number | null) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  });

  useEffect(() => {
    if (delayMs === null) return;
    const id = setInterval(() => savedCallback.current(), delayMs);
    return () => clearInterval(id);
  }, [delayMs]);
}
