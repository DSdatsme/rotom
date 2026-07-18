// Home / command center + generic page placeholder for out-of-scope routes.
const { useMemo: useMemoH } = React;

const KIND_ICON = { run: "zap", send: "send", draft: "pencil", reminder: "bell" };

function StatTile({ stat, accentOn, onClick }) {
  const showAccent = accentOn && stat.accent;
  return (
    <button className={"stat-tile" + (showAccent ? " accent" : "")} onClick={onClick}>
      <div className="stat-top">
        <span className="stat-label">{stat.label}</span>
        <Icon name="arrow-up" size={14} className="stat-go" />
      </div>
      <div className="stat-num-row">
        <span className="stat-num">{stat.value}</span>
        <span className="stat-sub">{stat.sub}</span>
      </div>
      <div className="stat-foot">
        {stat.critical ? (
          <span className="stat-chip tone-danger">
            <Icon name="alert-triangle" size={12} />
            {stat.critical} critical
          </span>
        ) : (
          <span className="stat-chip tone-muted">cleared</span>
        )}
      </div>
    </button>
  );
}

function StatTileSkeleton() {
  return (
    <div className="stat-tile skel">
      <div className="stat-top"><Skeleton w="92px" h={11} /></div>
      <div className="stat-num-row"><Skeleton w="48px" h={34} r={8} /></div>
      <div className="stat-foot"><Skeleton w="70px" h={18} r={9} /></div>
    </div>
  );
}

function ActivityRow({ a }) {
  return (
    <li className="act-row">
      <span className={"act-ic tone-" + a.status}>
        <Icon name={KIND_ICON[a.kind] || "clock"} size={15} />
      </span>
      <span className="act-main">
        <span className="act-title">{a.title}</span>
        <span className="act-meta mono">{a.meta}</span>
      </span>
      <span className="act-time">
        <span className="act-rel">{a.time}</span>
        <span className="act-abs mono">{a.at}</span>
      </span>
    </li>
  );
}

function ActivitySkeleton() {
  return (
    <ul className="act-list">
      {[0, 1, 2, 3].map((i) => (
        <li className="act-row" key={i}>
          <Skeleton w="28px" h={28} r={8} />
          <span className="act-main" style={{ gap: 7 }}>
            <Skeleton w={i % 2 ? "62%" : "48%"} h={12} />
            <Skeleton w="34%" h={10} />
          </span>
          <Skeleton w="44px" h={10} />
        </li>
      ))}
    </ul>
  );
}

function QuickActions({ onAction }) {
  const { QUICK_ACTIONS } = window.ROTOM;
  return (
    <div className="qa-grid">
      {QUICK_ACTIONS.map((a) => (
        <button className="qa-card" key={a.id} onClick={() => onAction(a.id)}>
          <span className="qa-ic"><Icon name={a.icon} size={16} /></span>
          <span className="qa-text">
            <span className="qa-label">{a.label}</span>
            <span className="qa-hint">{a.hint}</span>
          </span>
          <Kbd>{a.kbd}</Kbd>
        </button>
      ))}
    </div>
  );
}

function Home({ state, layout, accentOn, onNavigate, onAction, onRetry }) {
  const { COUNTS, ACTIVITY } = window.ROTOM;
  const loading = state === "loading";
  const error = state === "error";
  const empty = state === "empty";
  const stats = [COUNTS.inbox, COUNTS.drafts, COUNTS.reminders];

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });

  return (
    <div className="home" data-homelayout={layout}>
      <div className="home-greet">
        <h1 className="page-title">{greet}</h1>
        <p className="page-sub">Your assistant's workspace. Integrations land here as they come online.</p>
      </div>
      <div className="home-date mono">{today}</div>

      {error && (
        <div className="home-full">
          <ErrorBanner
            title="API unreachable"
            body="Can't reach the assistant backend. Counts and activity may be stale."
            onRetry={onRetry}
          />
        </div>
      )}

      {/* STATS */}
      <div className="home-stats">
        {loading
          ? [0, 1, 2].map((i) => <StatTileSkeleton key={i} />)
          : stats.map((s) => (
              <StatTile key={s.to} stat={empty ? { ...s, value: 0, critical: 0 } : s} accentOn={accentOn} onClick={() => onNavigate(s.to)} />
            ))}
      </div>

      {/* ACTIVITY */}
      <div className="home-activity">
        <Panel
          title="Recent activity"
          sub="Latest runs, sends, and reminders"
          actions={<button className="link-btn" onClick={() => onNavigate("runs")}>View runs<Icon name="chevron-right" size={13} /></button>}
          noPad
        >
          {loading ? (
            <ActivitySkeleton />
          ) : empty ? (
            <EmptyState
              icon="history"
              title="No activity yet"
              body="When the assistant triages mail or sends a reply, it shows up here."
              action={<Button variant="default" size="sm" icon="zap" onClick={() => onAction("triage")}>Trigger first run</Button>}
            />
          ) : (
            <ul className="act-list">
              {ACTIVITY.map((a) => <ActivityRow key={a.id} a={a} />)}
            </ul>
          )}
        </Panel>
      </div>

      {/* QUICK ACTIONS */}
      <div className="home-quick">
        <Panel title="Quick actions" sub="Also via ⌘K">
          {loading ? (
            <div className="qa-grid">
              {[0, 1, 2].map((i) => <div className="qa-card skel" key={i}><Skeleton w="100%" h={40} r={8} /></div>)}
            </div>
          ) : (
            <QuickActions onAction={onAction} />
          )}
        </Panel>

        <Panel title="Integrations" sub="Connect more sources">
          <div className="integ-list">
            {[
              { n: "GitHub", d: "Issues & PR triage", ic: "scroll" },
              { n: "Linear", d: "Sync tasks & cycles", ic: "bar-chart" },
              { n: "Calendar", d: "Schedule from email", ic: "clock" },
            ].map((it) => (
              <div className="integ-row" key={it.n}>
                <span className="integ-ic"><Icon name={it.ic} size={16} /></span>
                <span className="integ-text">
                  <span className="integ-name">{it.n}</span>
                  <span className="integ-desc">{it.d}</span>
                </span>
                <button className="btn btn-ghost btn-sm"><Icon name="plug" size={14} /><span>Connect</span></button>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

/* ----------------------------------------------- placeholder for other routes */
function ComingSoon({ item, onBack }) {
  return (
    <div className="page">
      <div className="home-greet">
        <h1 className="page-title">{item.label}</h1>
        <p className="page-sub">This section is part of the next design pass.</p>
      </div>
      <div>
        <Panel>
          <EmptyState
            icon={item.icon}
            title="Designed in the next pass"
            body="The shell, navigation, and Home command center come first. This page inherits the same Panel grammar, density, and state patterns once it's built."
            action={<Button variant="default" size="sm" icon="home" onClick={onBack}>Back to Overview</Button>}
          />
        </Panel>
      </div>
    </div>
  );
}

Object.assign(window, { Home, ComingSoon });
