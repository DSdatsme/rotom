// Global shell: collapsible sidebar + slim top bar.
const { useState: useStateS } = React;

function Wordmark({ collapsed }) {
  return (
    <div className="wordmark" title="rotom">
      <span className="glyph" aria-hidden="true">
        <span className="glyph-dot" />
      </span>
      {!collapsed && <span className="wordmark-text">rotom</span>}
    </div>
  );
}

function NavItem({ item, active, collapsed, indicator, onClick }) {
  return (
    <button
      className={"nav-item" + (active ? " active" : "") + " ind-" + indicator}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      data-tip={collapsed ? item.label : undefined}
    >
      <span className="nav-ind" aria-hidden="true" />
      <span className="nav-ic"><Icon name={item.icon} size={17} /></span>
      {!collapsed && <span className="nav-label">{item.label}</span>}
      {!collapsed && item.badge != null && <span className="nav-badge">{item.badge}</span>}
      {collapsed && item.badge != null && <span className="nav-badge-dot" />}
    </button>
  );
}

function Sidebar({ collapsed, route, onNavigate, indicator }) {
  const { NAV } = window.ROTOM;
  return (
    <aside className={"sidebar" + (collapsed ? " collapsed" : "")} aria-label="Primary">
      <div className="sidebar-head">
        <Wordmark collapsed={collapsed} />
      </div>
      <nav className="nav" aria-label="Sections">
        {NAV.map((group) => (
          <div className="nav-group" key={group.label}>
            {!collapsed ? (
              <div className="nav-group-label">{group.label}</div>
            ) : (
              <div className="nav-group-rule" aria-hidden="true" />
            )}
            {group.items.map((item) => (
              <NavItem
                key={item.id}
                item={item}
                active={route === item.id}
                collapsed={collapsed}
                indicator={indicator}
                onClick={() => onNavigate(item.id)}
              />
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">
        <button className="nav-item nav-add" data-tip={collapsed ? "Add integration" : undefined}>
          <span className="nav-ind" aria-hidden="true" />
          <span className="nav-ic"><Icon name="plus" size={17} /></span>
          {!collapsed && <span className="nav-label">Add integration</span>}
        </button>
      </div>
    </aside>
  );
}

function Breadcrumb({ crumbs, onCrumb }) {
  return (
    <nav className="crumb" aria-label="Breadcrumb">
      {crumbs.map((c, i) => {
        const last = i === crumbs.length - 1;
        return (
          <span className="crumb-part" key={i}>
            {i > 0 && <Icon name="chevron-right" size={14} className="crumb-sep" />}
            {last || !c.to ? (
              <span className={last ? "crumb-cur" : "crumb-anc"}>{c.label}</span>
            ) : (
              <button className="crumb-link" onClick={() => onCrumb(c.to)}>{c.label}</button>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function TopBar({ collapsed, onToggle, crumbs, onCrumb, onOpenPalette, apiStatus }) {
  const ok = apiStatus === "connected";
  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="icon-btn" onClick={onToggle} aria-label="Toggle sidebar" title="Toggle sidebar (⌘\\)">
          <Icon name="panel-left" size={17} />
        </button>
        <div className="topbar-divider" />
        <Breadcrumb crumbs={crumbs} onCrumb={onCrumb} />
      </div>
      <div className="topbar-right">
        <button className="cmdk-trigger" onClick={onOpenPalette} aria-label="Open command palette">
          <Icon name="search" size={15} />
          <span className="cmdk-trigger-text">Search or jump to…</span>
          <span className="cmdk-trigger-kbd"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
        </button>
        <div className={"api-status tone-" + (ok ? "success" : "danger")} title={ok ? "API connected · live" : "API unreachable"}>
          <StatusDot tone={ok ? "success" : "danger"} pulse={ok} />
          <span className="api-status-text">{ok ? "Live" : "Offline"}</span>
        </div>
      </div>
    </header>
  );
}

Object.assign(window, { Sidebar, TopBar, Breadcrumb, Wordmark });
