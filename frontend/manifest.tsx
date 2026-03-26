import { Brain, Key } from 'lucide-react'
import type { PluginManifest } from '@core/types/plugin'
import InsightSettingsPage from './src/pages/settings'
import InsightAccessPage from './src/pages/admin/access'

export const insightPlugin: PluginManifest = {
  id: 'insight',
  name: 'Yoink Insight',

  routes: [
    { path: '/insight/settings',      element: <InsightSettingsPage /> },
    { path: '/admin/insight-access',  element: <InsightAccessPage />, minRole: 'admin' },
  ],

  navGroups: [
    {
      items: [
        { label: 'AI Settings', path: '/insight/settings', icon: <Brain className="h-4 w-4" /> },
      ],
    },
    {
      label: 'Admin',
      collapsible: true,
      defaultOpen: true,
      minRole: ['owner', 'admin'],
      items: [
        {
          label: 'Insight Access',
          path: '/admin/insight-access',
          icon: <Key className="h-4 w-4" />,
          minRole: ['owner', 'admin'],
        },
      ],
    },
  ],

  resources: [
    { name: 'insight-settings', list: '/insight/settings' },
    { name: 'insight-access',   list: '/admin/insight-access', meta: { label: 'Insight Access' } },
  ],
}
