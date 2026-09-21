import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  FileText,
  Upload,
  ClipboardCheck,
  Database,
  Bot,
  BarChart3,
  Tags,
  FileBarChart,
  ScrollText,
  Settings,
  Mountain,
  Search,
  ShieldAlert,
  Users,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'

type NavItem = {
  to: string
  label: string
  icon: typeof LayoutDashboard
  permission?: string
}

const nav: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/documents', label: 'Documents', icon: FileText, permission: 'documents.read' },
  { to: '/upload', label: 'Upload', icon: Upload, permission: 'documents.upload' },
  { to: '/review', label: 'Review Queue', icon: ClipboardCheck, permission: 'review.act' },
  { to: '/validation', label: 'Validation', icon: ShieldAlert, permission: 'documents.read' },
  { to: '/search', label: 'Semantic Search', icon: Search, permission: 'search' },
  { to: '/explorer', label: 'Data Explorer', icon: Database, permission: 'explore' },
  { to: '/geology', label: 'Geological Explorer', icon: Mountain, permission: 'explore' },
  { to: '/assistant', label: 'AI Assistant', icon: Bot, permission: 'assistant' },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, permission: 'analytics' },
  { to: '/topics', label: 'Topics', icon: Tags, permission: 'topics' },
  { to: '/reports', label: 'Reports', icon: FileBarChart, permission: 'reports.read' },
  { to: '/audit', label: 'Audit Logs', icon: ScrollText, permission: 'audit.read' },
  { to: '/users', label: 'Users', icon: Users, permission: 'users.manage' },
  { to: '/settings', label: 'Settings', icon: Settings, permission: 'settings.read' },
]

export function Sidebar() {
  const { hasPermission, user } = useAuth()
  const visible = nav.filter((item) => !item.permission || hasPermission(item.permission))

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-ore-700/50 bg-ore-900/90 backdrop-blur-sm">
      <div className="border-b border-ore-700/50 px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ore-850 ring-1 ring-copper-500/40">
            <Mountain className="h-5 w-5 text-copper-400" strokeWidth={2.25} />
          </div>
          <div>
            <p className="font-display text-xl leading-none tracking-wide text-ore-100">
              MINEINTEL
            </p>
            <p className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.22em] text-copper-400">
              AI Platform
            </p>
          </div>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-ore-400">
          Mining Document Intelligence · SIH26023
        </p>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {visible.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              [
                'group flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors duration-200',
                isActive
                  ? 'bg-copper-500/15 text-copper-300 ring-1 ring-copper-500/30'
                  : 'text-ore-300 hover:bg-ore-800/80 hover:text-ore-100',
              ].join(' ')
            }
          >
            <Icon className="h-4 w-4 shrink-0 opacity-80" />
            <span className="font-medium">{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-ore-700/50 px-4 py-4">
        <div className="panel-inset rounded-md px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-signal-green animate-pulse-soft" />
            <span className="text-xs text-ore-300">
              {user?.anonymous ? 'Demo mode · live database' : `${user?.role || 'user'} · authenticated`}
            </span>
          </div>
        </div>
      </div>
    </aside>
  )
}
