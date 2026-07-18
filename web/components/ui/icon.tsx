import {
  House,
  Inbox,
  PenLine,
  History,
  Bell,
  Sparkles,
  ChartColumn,
  ScrollText,
  TriangleAlert,
  CornerDownLeft,
  Info,
  Minus,
  CircleDot,
  CircleCheck,
  CircleSlash,
  CircleX,
  Loader,
  Shield,
  type LucideIcon,
} from "lucide-react";

/** Map of icon-name strings (emitted by view models / nav config) → lucide components. */
const ICONS: Record<string, LucideIcon> = {
  House,
  Inbox,
  PenLine,
  History,
  Bell,
  Sparkles,
  ChartColumn,
  ScrollText,
  TriangleAlert,
  CornerDownLeft,
  Info,
  Minus,
  CircleDot,
  CircleCheck,
  CircleSlash,
  CircleX,
  Loader,
  Shield,
};

export function Icon({
  name,
  className,
  size,
}: {
  name: string;
  className?: string;
  size?: number;
}) {
  const Cmp = ICONS[name] ?? Info;
  return <Cmp className={className} size={size} aria-hidden />;
}
