import type { EmailItem } from "@/lib/api";
import { categoryMeta } from "@/lib/view/email";
import { Icon } from "@/components/ui/icon";

/** Mock CSS tone tokens: our "brand" maps to the mock's "accent". */
function toneCls(tone: string): string {
  return tone === "brand" ? "accent" : tone;
}

export function CategoryBadge({ category }: { category: EmailItem["category"] }) {
  const c = categoryMeta(category);
  return (
    <span className={"cat-badge tone-" + toneCls(c.tone)}>
      <Icon name={c.icon} size={12} />
      {c.label}
    </span>
  );
}
