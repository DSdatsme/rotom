"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  getSoul,
  updateSoul,
  bulkEmailStatus,
  cancelReminder,
  createReminder,
  parseReminder,
  patchDraft,
  postDraftAction,
  regenerateEmailDraft,
  createDraft,
  postDraftMessage,
  saveToGmail,
  triggerRun,
  type ReminderProposal,
  type DraftItem,
} from "@/lib/api";

export async function setEmailsStatus(
  ids: number[],
  status: "open" | "done" | "irrelevant",
): Promise<{ ok: boolean; error?: string }> {
  try {
    await bulkEmailStatus(ids, status);
    revalidatePath("/email");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "update failed" };
  }
}

export async function regenerateDraft(emailId: number): Promise<{ ok: boolean; error?: string }> {
  try {
    await regenerateEmailDraft(emailId);
    revalidatePath(`/email/${emailId}`);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "regenerate failed" };
  }
}

export async function saveDraft(id: number, update: { body?: string; subject?: string | null; to_addr?: string | null; account?: string | null; attachments?: string[] }): Promise<{ ok: boolean; error?: string }> {
  try {
    await patchDraft(id, update);
    revalidatePath(`/email/drafts/${id}`);
    revalidatePath(`/drafts/${id}`);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "save failed" };
  }
}

export async function sendDraft(id: number, update: { body?: string; subject?: string | null; to_addr?: string | null; account?: string | null; attachments?: string[] }, rotomFooter?: boolean): Promise<{ ok: boolean; error?: string }> {
  try {
    // Persist any last edits, then send — the explicit human action is the HITL gate.
    await patchDraft(id, update);
    await postDraftAction(id, "send", rotomFooter);
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "send failed" };
  }
  revalidatePath("/email/drafts");
  redirect("/email/drafts?sent=1");
}

export async function createDraftAction(kind: "reply" | "outreach"): Promise<{ ok: boolean; draft?: DraftItem; error?: string }> {
  try {
    const draft = await createDraft(kind);
    return { ok: true, draft };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "create failed" };
  }
}

export async function sendMessageAction(id: number, content: string): Promise<{ ok: boolean; draft?: DraftItem; error?: string }> {
  try {
    const draft = await postDraftMessage(id, content);
    revalidatePath(`/email/drafts/${id}`);
    revalidatePath(`/drafts/${id}`);
    return { ok: true, draft };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "send message failed" };
  }
}

export async function saveToGmailAction(id: number, update?: { body?: string; subject?: string | null; to_addr?: string | null; account?: string | null; attachments?: string[] }, rotomFooter?: boolean): Promise<{ ok: boolean; error?: string }> {
  try {
    if (update) {
      await patchDraft(id, update);
    }
    await saveToGmail(id, rotomFooter);
    revalidatePath(`/email/drafts/${id}`);
    revalidatePath(`/drafts/${id}`);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "save to gmail failed" };
  }
}

export async function discardDraftInline(id: number): Promise<{ ok: boolean; error?: string }> {
  // Discard from a list/detail context — refresh in place, no redirect.
  try {
    await postDraftAction(id, "discard");
    revalidatePath("/email/drafts");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "discard failed" };
  }
}

export async function parseReminderAction(
  message: string,
): Promise<{ ok: boolean; proposal?: ReminderProposal; error?: string }> {
  try {
    const proposal = await parseReminder(message);
    return { ok: true, proposal };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "parse failed" };
  }
}

export async function createReminderAction(
  text: string,
  fireAt: string,
  recurrenceCron: string = "",
): Promise<{ ok: boolean; error?: string }> {
  try {
    await createReminder(text, fireAt, recurrenceCron);
    revalidatePath("/reminders");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "create failed" };
  }
}

export async function cancelReminderAction(id: number): Promise<{ ok: boolean; error?: string }> {
  try {
    await cancelReminder(id);
    revalidatePath("/reminders");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "cancel failed" };
  }
}

export async function discardDraft(id: number): Promise<{ ok: boolean; error?: string }> {
  try {
    await postDraftAction(id, "discard");
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "discard failed" };
  }
  revalidatePath("/email/drafts");
  redirect("/email/drafts");
}

export async function updateSoulAction(content: string): Promise<{ ok: boolean; error?: string }> {
  try {
    await updateSoul(content);
    revalidatePath("/soul");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "update failed" };
  }
}

export async function triggerRunAction(): Promise<{ ok: boolean; error?: string }> {
  try {
    await triggerRun();
    // wait a moment for the background APScheduler to actually create the run in DB
    await new Promise((resolve) => setTimeout(resolve, 500));
    revalidatePath("/email/runs");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "trigger failed" };
  }
}
