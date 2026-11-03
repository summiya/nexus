import type { ReactNode } from "react";

export type DashboardIconName =
  | "overview"
  | "chat"
  | "projects"
  | "knowledge"
  | "files"
  | "artifacts"
  | "agents"
  | "tools"
  | "incidents"
  | "settings"
  | "usage"
  | "profile"
  | "preferences"
  | "security"
  | "search"
  | "arrow"
  | "logout"
  | "menu"
  | "close"
  | "sparkle"
  | "check"
  | "chevron";

interface DashboardIconProps {
  name: DashboardIconName;
  size?: number;
  className?: string;
}

const paths: Record<DashboardIconName, ReactNode> = {
  overview: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.4" />
      <rect x="14" y="3" width="7" height="7" rx="1.4" />
      <rect x="3" y="14" width="7" height="7" rx="1.4" />
      <rect x="14" y="14" width="7" height="7" rx="1.4" />
    </>
  ),
  chat: (
    <path d="M20 11.4a7.9 7.9 0 0 1-8.1 7.7 9.5 9.5 0 0 1-3.5-.6L4 20l1.3-4a7.4 7.4 0 0 1-2.1-4.6 8.1 8.1 0 0 1 8.7-8.1A8.2 8.2 0 0 1 20 11.4Z" />
  ),
  projects: (
    <>
      <path d="M3.5 7.5V6a2 2 0 0 1 2-2h4.2l2 2.1h6.8a2 2 0 0 1 2 2v10.2a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" />
      <path d="M3.5 10h17" />
    </>
  ),
  knowledge: (
    <>
      <ellipse cx="12" cy="5.3" rx="8.5" ry="3.2" />
      <path d="M3.5 5.3v6.4c0 1.8 3.8 3.2 8.5 3.2s8.5-1.4 8.5-3.2V5.3M3.5 11.7v6.1c0 1.8 3.8 3.2 8.5 3.2s8.5-1.4 8.5-3.2v-6.1" />
    </>
  ),
  files: (
    <>
      <path d="M6 2.8h8l5 5V20a1.6 1.6 0 0 1-1.6 1.6H6A1.6 1.6 0 0 1 4.4 20V4.4A1.6 1.6 0 0 1 6 2.8Z" />
      <path d="M14 3v5h5M8 12h8M8 16h8" />
    </>
  ),
  artifacts: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M4 9h16M10 9v11M7 6.5h.01" />
    </>
  ),
  agents: (
    <>
      <path d="m12 2.5 1.8 6.3L20 11l-6.2 2.1L12 19.5l-1.8-6.4L4 11l6.2-2.2Z" />
      <path d="m19.5 17 .7 2 2 1-.7.3-1.3 1.1-.7-1.5-1.5-.6Z" />
    </>
  ),
  tools: (
    <>
      <path d="M7.4 10.2A4.8 4.8 0 0 1 12 4c.6 0 1.3.1 1.9.4L11 7.3l.5 3 3.1.5 2.9-2.9A4.8 4.8 0 0 1 12.8 14l-6.6 6.6a2.1 2.1 0 0 1-3-3Z" />
    </>
  ),
  incidents: (
    <>
      <path d="M10.3 3.5a2 2 0 0 1 3.4 0l8 14.2a2 2 0 0 1-1.7 3H4a2 2 0 0 1-1.7-3Z" />
      <path d="M12 9v5M12 17h.01" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3.1" />
      <path d="m9.9 2.8-.5 2-1.7 1-1.9-.6-1.9 3.3 1.4 1.4v2l-1.4 1.4 1.9 3.3 1.9-.6 1.7 1 .5 2h4.2l.5-2 1.7-1 1.9.6 1.9-3.3-1.4-1.4v-2l1.4-1.4-1.9-3.3-1.9.6-1.7-1-.5-2Z" />
    </>
  ),
  usage: (
    <>
      <path d="M4 20V11M10 20V5M16 20v-8M22 20v-12M2 20h22" />
    </>
  ),
  profile: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c.6-4.5 3.2-7 8-7s7.4 2.5 8 7" />
    </>
  ),
  preferences: (
    <>
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.5 5.5l2.1 2.1M16.4 16.4l2.1 2.1M18.5 5.5l-2.1 2.1M7.6 16.4l-2.1 2.1" />
      <circle cx="12" cy="12" r="4" />
    </>
  ),
  security: (
    <>
      <path d="M12 2.5 20 6v5.7c0 5.1-3.2 8.5-8 10-4.8-1.5-8-4.9-8-10V6Z" />
      <path d="m8.5 12 2.4 2.5 4.7-5" />
    </>
  ),
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.8" />
      <path d="m16 16 5.3 5.3" />
    </>
  ),
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  logout: (
    <>
      <path d="M10 3.5H6A2.5 2.5 0 0 0 3.5 6v12A2.5 2.5 0 0 0 6 20.5h4M13 7l5 5-5 5m5-5H8" />
    </>
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  close: <path d="M5 5 19 19M19 5 5 19" />,
  sparkle: (
    <>
      <path d="m12 2 1.7 7.3L21 11l-7.3 1.7L12 20l-1.7-7.3L3 11l7.3-1.7Z" />
    </>
  ),
  check: <path d="m4 12 5 5L20 6" />,
  chevron: <path d="m6 9 6 6 6-6" />,
};

export function DashboardIcon({
  name,
  size = 18,
  className,
}: DashboardIconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}
