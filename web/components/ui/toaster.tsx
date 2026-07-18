"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { toneText } from "@/lib/tone";
import type { Tone } from "@/lib/view/email";
import { Icon } from "@/components/ui/icon";

interface Toast {
  id: string;
  msg: string;
  tone?: Tone;
  icon?: string;
}

interface ToastInput {
  tone?: Tone;
  icon?: string;
}

const ToastContext = React.createContext<(msg: string, opts?: ToastInput) => void>(() => {});

export function useToast() {
  return React.useContext(ToastContext);
}

let counter = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const toast = React.useCallback((msg: string, opts: ToastInput = {}) => {
    const id = `t${++counter}`;
    setToasts((ts) => [...ts, { id, msg, ...opts }]);
    setTimeout(() => setToasts((ts) => ts.filter((t) => t.id !== id)), 2800);
  }, []);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div
        className="pointer-events-none fixed right-4 bottom-4 z-50 flex flex-col items-end gap-2"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-center gap-2 rounded-lg border border-border bg-card-3 px-3 py-2 text-sm text-foreground shadow-lg"
          >
            {t.icon && <Icon name={t.icon} size={15} className={cn(t.tone && toneText[t.tone])} />}
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
