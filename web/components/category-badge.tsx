import type { EmailItem } from "@/lib/api";
import { categoryMeta } from "@/lib/view/email";
import { toneCls } from "@/lib/tone";
import { Icon } from "@/components/ui/icon";

export function CategoryBadge({ category }: { category: EmailItem["category"] }) {
  const c = categoryMeta(category);
  return (
    <span className={"cat-badge tone-" + toneCls(c.tone)}>
      <Icon name={c.icon} size={12} />
      {c.label}
    </span>
  );
}
