import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { RunSummary } from "../api/types";
import { Icon, type IconName } from "../components/Icons";
import { Badge } from "../components/ui";
import { STATUS_LABEL, formatDuration, elapsedSince } from "../utils/format";
import { useCurrentRun } from "../store/currentRun";

const NAV: Array<{ to: string; label: string; icon: IconName; match: string }> = [
  { to: "/console", label: "运行控制台", icon: "console", match: "/console" },
  { to: "/new", label: "新建任务", icon: "plus", match: "/new" },
  { to: "/settings/nodes", label: "节点配置", icon: "settings", match: "/settings" },
  { to: "/history", label: "历史运行", icon: "history", match: "/history" },
  { to: "/report", label: "输出报告", icon: "report", match: "/report" },
];

export function AppShell({ children }: { children: ReactNode }): ReactNode {
  const location = useLocation();
  const navigate = useNavigate();
  const { snapshot } = useCurrentRun();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [theme, setTheme] = useState<string>(
    () => document.documentElement.dataset.theme ?? "dark",
  );

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("mars.theme", next);
    setTheme(next);
  };

  useEffect(() => {
    let active = true;
    api
      .listRuns()
      .then((items) => {
        if (active) setRuns(items);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [location.pathname]);

  const latest = runs[0];
  const currentFromRoute = (() => {
    const match = /^\/(?:console|report)\/([^/]+)/.exec(location.pathname);
    return match?.[1];
  })();
  const current = currentFromRoute
    ? runs.find((item) => item.thread_id === currentFromRoute) ?? latest
    : latest;

  const target = (base: string) => (current ? `${base}/${current.thread_id}` : "#");

  return (
    <div className="shell">
      <nav className="nav">
        <div className="nav__brand">
          <span className="nav__logo">M</span>
          <div>
            <strong>MARS-Graph</strong>
            <span>提示词优化工作台</span>
          </div>
        </div>

        <ul className="nav__list">
          {NAV.map((item) => {
            const to =
              item.match === "/console" || item.match === "/report" ? target(item.to) : item.to;
            const disabled = to === "#";
            return (
              <li key={item.label}>
                {disabled ? (
                  <span className="nav__item is-disabled" title="先创建一个优化任务">
                    <Icon name={item.icon} size={16} />
                    {item.label}
                    <Icon name="lock" size={12} className="nav__lock" />
                  </span>
                ) : (
                  <NavLink
                    to={to}
                    className={({ isActive }) =>
                      `nav__item${isActive || location.pathname.startsWith(item.match) ? " is-active" : ""}`
                    }
                  >
                    <Icon name={item.icon} size={16} />
                    {item.label}
                  </NavLink>
                )}
              </li>
            );
          })}
        </ul>

        <div className="nav__section">
          <span className="nav__section-title">当前任务</span>
          {current ? (
            <button
              type="button"
              className="nav__run"
              onClick={() => navigate(`/console/${current.thread_id}`)}
            >
              <span className="nav__run-name">{current.name}</span>
              <span className="nav__run-id mono">{current.thread_id}</span>
              <span
                className={`nav__run-status nav__run-status--${
                  snapshot && snapshot.thread_id === current.thread_id
                    ? snapshot.status
                    : current.status
                }`}
              >
                {STATUS_LABEL[
                  snapshot && snapshot.thread_id === current.thread_id
                    ? snapshot.status
                    : current.status
                ]}
              </span>
            </button>
          ) : (
            <p className="nav__empty">还没有运行记录</p>
          )}
        </div>

        {snapshot?.breakpoints?.length ? (
          <div className="nav__section">
            <span className="nav__section-title">断点 {snapshot.breakpoints.length}</span>
            <ul className="nav__bps">
              {snapshot.breakpoints.map((edge) => (
                <li key={edge}>
                  <Icon name="breakpoint" size={12} />
                  <code>{edge}</code>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="nav__foot">
          {snapshot ? (
            <div className="nav__foot-row">
              <Badge tone={snapshot.status === "failed" ? "error" : "muted"}>
                TSC {snapshot.values.tsc_count ?? 0}/{snapshot.tsc_max}
              </Badge>
              <Badge tone="muted">
                M {snapshot.values.m_count ?? 0}/{snapshot.m_max}
              </Badge>
              <span className="nav__elapsed mono">
                {formatDuration(
                  elapsedSince(snapshot.created_at, snapshot.finished_at || undefined),
                )}
              </span>
            </div>
          ) : null}
          <a className="nav__doc" href="/docs" target="_blank" rel="noreferrer">
            <Icon name="external" size={13} />
            API 文档
          </a>
          <button type="button" className="nav__doc" onClick={toggleTheme}>
            <Icon name="spark" size={13} />
            {theme === "dark" ? "切换浅色" : "切换深色"}
          </button>
        </div>
      </nav>

      <main className="shell__main">{children}</main>
    </div>
  );
}
