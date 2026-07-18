"use client";

import { useMemo, useState, useTransition } from "react";
import { Loader2, Save, Check } from "lucide-react";
import { updateSoulAction } from "@/lib/actions";
import { Button } from "@/components/ui/button";

export function SoulEditor({ initialContent }: { initialContent: string }) {
  const [content, setContent] = useState(initialContent);
  const [isPending, startTransition] = useTransition();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const { words, samples } = useMemo(() => {
    const trimmed = content.trim();
    // Count labeled "**Sample N**" blocks; fall back to ">"-quoted lines.
    const headers = content.match(/^\s*\*\*\s*sample\b/gim) ?? [];
    const quotes = content.match(/^>/gm) ?? [];
    return {
      words: trimmed ? trimmed.split(/\s+/).length : 0,
      samples: headers.length || quotes.length,
    };
  }, [content]);

  const handleSave = () => {
    startTransition(async () => {
      setError("");
      setSaved(false);
      const res = await updateSoulAction(content);
      if (res.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } else {
        setError(res.error || "Failed to save SOUL.");
      }
    });
  };

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <span className="mono text-xs text-faint">persona.md</span>
          <span className="mono text-xs text-faint">
            {words} words ·{" "}
            <span
              title="Writing samples — labeled “**Sample N: …**” blocks (or lines starting with “>”). Real messages you’ve written so rotom can echo your voice."
              className="cursor-help underline decoration-dotted underline-offset-2"
            >
              {samples} sample{samples === 1 ? "" : "s"}
            </span>
          </span>
        </div>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          spellCheck
          className="min-h-[480px] w-full resize-y bg-transparent p-4 font-mono text-sm leading-relaxed text-fg-2 outline-none placeholder:text-faint"
          placeholder="Start with who you are…"
        />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex items-center justify-end gap-3">
        {saved && (
          <span className="flex items-center gap-1 text-xs text-success">
            <Check className="size-3.5" /> Saved
          </span>
        )}
        <Button onClick={handleSave} disabled={isPending}>
          {isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          Save SOUL
        </Button>
      </div>
    </div>
  );
}
