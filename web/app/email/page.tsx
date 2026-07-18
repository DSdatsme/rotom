import { getAccounts, getEmails } from "@/lib/api";
import { toEmailView } from "@/lib/view/email";
import { EmailFilters, type EmailFilterValues } from "@/components/email-filters";
import { EmailTable } from "@/components/email-table";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Kbd } from "@/components/ui/kbd";

export const dynamic = "force-dynamic";

const DEFAULTS = { category: "critical,needs_reply", status: "open" }; // action required & open

type SearchParams = Partial<EmailFilterValues> & { f?: string };

export default async function EmailPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const untouched = !sp.f; // "f" marks that the user changed filters explicitly
  const values: EmailFilterValues = {
    category: sp.category ?? (untouched ? DEFAULTS.category : ""),
    status: sp.status ?? (untouched ? DEFAULTS.status : ""),
    account: sp.account ?? "",
    suspicious: sp.suspicious ?? "",
    urgency: sp.urgency ?? "",
    received_from: sp.received_from ?? "",
    received_to: sp.received_to ?? "",
    triaged_from: sp.triaged_from ?? "",
    triaged_to: sp.triaged_to ?? "",
  };

  let emails, accounts;
  try {
    [emails, accounts] = await Promise.all([getEmails(values), getAccounts()]);
  } catch (e) {
    return (
      <Panel>
        <EmptyState
          icon="TriangleAlert"
          title="API unreachable"
          body={e instanceof Error ? e.message : "unknown error"}
        />
      </Panel>
    );
  }

  const now = Date.now();
  const views = emails.map((e) => toEmailView(e, now));

  return (
    <div className="triage">
      <div className="triage-head">
        <div className="triage-title-wrap">
          <h1 className="page-title">Inbox triage</h1>
          <p className="count-line">
            <span className="mono">{views.length}</span> {views.length === 1 ? "email" : "emails"}
          </p>
        </div>
        <span className="kbd-hint">
          <Kbd>j</Kbd>
          <Kbd>k</Kbd> move · <Kbd>x</Kbd> select · <Kbd>e</Kbd> done
        </span>
      </div>

      <EmailFilters accounts={accounts} values={values} />

      {views.length === 0 ? (
        <div className="tbl-wrap">
          <EmptyState
            icon="Inbox"
            title="No emails match these filters"
            body="Try widening the category or status filters, or reset to the default triage view."
          />
        </div>
      ) : (
        <EmailTable emails={views} />
      )}
    </div>
  );
}
