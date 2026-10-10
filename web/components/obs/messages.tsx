import type { ChatMessage } from "@/lib/view/trace";
import { cn } from "@/lib/utils";

const ROLE_STYLE: Record<string, string> = {
  system: "border-slate/40 bg-slate/8",
  user: "border-border bg-card-3",
  assistant: "border-brand-line bg-brand-soft",
  tool: "border-border bg-card",
};

export function ChatMessages({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="space-y-2">
      {messages.map((m, i) => (
        <div key={i} className={cn("rounded-md border px-3 py-2", ROLE_STYLE[m.role] ?? ROLE_STYLE.tool)}>
          <div className="mb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">{m.role}</div>
          {m.content && (
            <pre className="max-h-80 overflow-auto font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
              {m.content}
            </pre>
          )}
          {m.tool_calls?.map((c, j) => (
            <pre key={j} className="mt-1 overflow-x-auto rounded bg-card px-2 py-1 font-mono text-xs">
              → {c.name}({JSON.stringify(c.args)})
            </pre>
          ))}
        </div>
      ))}
    </div>
  );
}
