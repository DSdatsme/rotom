import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { AppSidebar } from "@/components/app-sidebar";
import { AppShell } from "@/components/app-shell";
import { SidebarProvider } from "@/components/ui/sidebar";
import { ToastProvider } from "@/components/ui/toaster";
import { getDrafts, getEmails, getReminders, getRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Pending counts per nav href → drives the notification dots. Never throws. */
async function navCounts(): Promise<Record<string, number>> {
  const [emails, drafts, reminders, runs] = await Promise.all([
    getEmails({ category: "critical,needs_reply", status: "open" }).catch(() => []),
    getDrafts().catch(() => []),
    getReminders("pending").catch(() => []),
    getRuns(50).catch(() => []),
  ]);
  return {
    "/email": emails.length,
    "/email/drafts": drafts.length,
    "/reminders": reminders.length,
    "/email/runs": runs.filter((r) => r.status === "running").length,
  };
}

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "rotom",
  description: "Personal AI assistant dashboard",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const counts = await navCounts();
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}
    >
      <body className="min-h-full">
        <ToastProvider>
          <SidebarProvider>
            <AppSidebar counts={counts} />
            <AppShell>{children}</AppShell>
          </SidebarProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
