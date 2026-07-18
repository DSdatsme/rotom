"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Icon } from "@/components/ui/icon";
import { RotomMark } from "@/components/rotom-mark";
import { NAV_SECTIONS } from "@/lib/nav";

export function AppSidebar({ counts = {} }: { counts?: Record<string, number> }) {
  const pathname = usePathname();
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <Link
          href="/"
          data-rotom-hover
          aria-label="rotom — home"
          className="flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-sidebar-accent group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
        >
          <RotomMark size={34} className="shrink-0" />
          <span className="text-[21px] font-semibold tracking-[-0.02em] group-data-[collapsible=icon]:hidden">rotom</span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        {NAV_SECTIONS.map((section) => (
          <SidebarGroup key={section.label}>
            <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {section.items.map((item) => (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      render={<Link href={item.href} />}
                      isActive={pathname === item.href}
                      tooltip={item.title}
                      className="relative before:absolute before:top-1/2 before:left-0 before:h-4 before:w-0.5 before:-translate-y-1/2 before:rounded-r-full before:bg-brand before:opacity-0 data-active:before:opacity-100 data-active:[&_svg]:text-brand"
                    >
                      <span className="relative flex shrink-0">
                        <Icon name={item.icon} />
                        {/* Dot only in the collapsed icon rail; expanded shows the count badge */}
                        {(counts[item.href] ?? 0) > 0 && (
                          <span className="absolute -top-0.5 -right-0.5 hidden size-1.5 rounded-full bg-brand ring-2 ring-sidebar group-data-[collapsible=icon]:block" />
                        )}
                      </span>
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                    {(counts[item.href] ?? 0) > 0 && (
                      <SidebarMenuBadge>{counts[item.href]}</SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
    </Sidebar>
  );
}
