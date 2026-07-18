Create a Conversational Draft Composer.

It should have:
1. A database model for `Draft` and `DraftMessage` (to track chat history).
2. A single composer service that takes a context (history, original email, attachments) and uses an LLM to generate a JSON response with the drafted body, subject, and a note about the changes.
3. A Next.js two-pane UI: left side is a chat thread, right side is an editable preview of the draft and toggles for attachments.
4. Support for saving to Gmail directly by creating multipart MIME drafts. Use `gmail.compose` scope. Send deletes the stale Gmail draft.
5. All pasted text and source emails must be wrapped in `<untrusted_content>` tags.
