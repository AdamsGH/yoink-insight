import { Brain, Link } from 'lucide-react'
import type { PluginManifest } from '@core/types/plugin'
import InsightSettingsPage from './src/pages/settings'
import TldrConfigPage from './src/pages/admin/TldrConfigPage'

export const insightPlugin: PluginManifest = {
  id: 'insight',
  name: 'Yoink Insight',

  routes: [
    { path: '/insight/settings', element: <InsightSettingsPage /> },
    { path: '/admin/insight-tldr', element: <TldrConfigPage /> },
  ],

  navGroups: [
    {
      items: [
        { label: 'AI', i18nKey: 'nav.ai', path: '/insight/settings', icon: <Brain className="h-4 w-4" /> },
      ],
    },
    {
      label: 'Admin',
      collapsible: true,
      defaultOpen: true,
      minRole: ['owner', 'admin'],
      items: [
        { label: 'TL;DR Config', i18nKey: 'nav.tldr_config', path: '/admin/insight-tldr', icon: <Link className="h-4 w-4" />, minRole: ['owner', 'admin'] },
      ],
    },
  ],

  resources: [
    { name: 'insight-settings', list: '/insight/settings' },
    { name: 'insight-tldr-config', list: '/admin/insight-tldr' },
  ],
}
