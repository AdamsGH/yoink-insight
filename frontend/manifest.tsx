import { Brain } from 'lucide-react'
import type { PluginManifest } from '@core/types/plugin'
import InsightSettingsPage from './src/pages/settings'

export const insightPlugin: PluginManifest = {
  id: 'insight',
  name: 'Yoink Insight',

  routes: [
    { path: '/insight/settings', element: <InsightSettingsPage /> },
  ],

  navGroups: [
    {
      items: [
        { label: 'AI Settings', i18nKey: 'nav.ai_settings', path: '/insight/settings', icon: <Brain className="h-4 w-4" />, requiredFeature: 'insight:summary' },
      ],
    },
  ],

  resources: [
    { name: 'insight-settings', list: '/insight/settings' },
  ],
}
