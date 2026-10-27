import { lazy, Suspense, type CSSProperties } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppSidebar } from '@/components/shell/AppSidebar'
import { ContextHeader } from '@/components/shell/ContextHeader'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { CommandScreen } from '@/screens/Command/CommandScreen'
import { CommandPalette } from '@/components/shell/CommandPalette'
import { Skel, SkelMasthead } from '@/components/shell/ScreenStates'

// Every screen but Command is its own chunk: the three.js, leaflet and chart
// libraries only download when the screen that needs them is opened.
const MatchweekScreen = lazy(() => import('@/screens/Matchweek/MatchweekScreen').then((m) => ({ default: m.MatchweekScreen })))
const ClubScreen = lazy(() => import('@/screens/Profile/ClubScreen').then((m) => ({ default: m.ClubScreen })))
const MatchScreen = lazy(() => import('@/screens/Profile/MatchScreen').then((m) => ({ default: m.MatchScreen })))
const PlayerScreen = lazy(() => import('@/screens/Profile/PlayerScreen').then((m) => ({ default: m.PlayerScreen })))
const MyTeamScreen = lazy(() => import('@/screens/MyTeam/MyTeamScreen').then((m) => ({ default: m.MyTeamScreen })))
const PlanScreen = lazy(() => import('@/screens/Plan/PlanScreen').then((m) => ({ default: m.PlanScreen })))
const ReceiptsScreen = lazy(() => import('@/screens/Receipts/ReceiptsScreen').then((m) => ({ default: m.ReceiptsScreen })))
const AtlasScreen = lazy(() => import('@/screens/Atlas/AtlasScreen').then((m) => ({ default: m.AtlasScreen })))
const TableScreen = lazy(() => import('@/screens/Table/TableScreen').then((m) => ({ default: m.TableScreen })))
const FootballScreen = lazy(() => import('@/screens/Football/FootballScreen').then((m) => ({ default: m.FootballScreen })))
const AuditScreen = lazy(() => import('@/screens/Audit/AuditScreen').then((m) => ({ default: m.AuditScreen })))
const FieldScreen = lazy(() => import('@/screens/Field/FieldScreen').then((m) => ({ default: m.FieldScreen })))
const CompareScreen = lazy(() => import('@/screens/Compare/CompareScreen').then((m) => ({ default: m.CompareScreen })))
const ExplorerScreen = lazy(() => import('@/screens/Explorer/ExplorerScreen').then((m) => ({ default: m.ExplorerScreen })))
const PreviewsScreen = lazy(() => import('@/screens/Previews/PreviewsScreen').then((m) => ({ default: m.PreviewsScreen })))
const DeskScreen = lazy(() => import('@/screens/Desk/DeskScreen').then((m) => ({ default: m.DeskScreen })))
const ScoutScreen = lazy(() => import('@/screens/Scout/ScoutScreen').then((m) => ({ default: m.ScoutScreen })))
const AdvancedScreen = lazy(() => import('@/screens/Advanced/AdvancedScreen').then((m) => ({ default: m.AdvancedScreen })))
const LeaguesScreen = lazy(() => import('@/screens/Leagues/LeaguesScreen').then((m) => ({ default: m.LeaguesScreen })))
const LiveScreen = lazy(() => import('@/screens/Live/LiveScreen').then((m) => ({ default: m.LiveScreen })))

function RouteFallback() {
  return (
    <div className="animate-pulse pb-16">
      <SkelMasthead />
      <div className="space-y-3 px-10 py-8">
        <Skel className="h-40 w-full" />
        <Skel className="h-64 w-full" />
      </div>
    </div>
  )
}

function App() {
  return (
    <SidebarProvider style={{ '--sidebar-width': '13rem' } as CSSProperties}>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <ContextHeader />
        <main className="flex-1 overflow-auto">
          <div className="screen-frame">
          <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<CommandScreen />} />
            <Route path="/my-team" element={<MyTeamScreen />} />
            <Route path="/plan" element={<PlanScreen />} />
            <Route path="/receipts" element={<ReceiptsScreen />} />
            <Route path="/matchweek" element={<MatchweekScreen />} />
            <Route path="/club/:id" element={<ClubScreen />} />
            <Route path="/player/:id" element={<PlayerScreen />} />
            <Route path="/match/:id" element={<MatchScreen />} />
            <Route path="/football" element={<FootballScreen />} />
            <Route path="/atlas" element={<AtlasScreen />} />
            <Route path="/table" element={<TableScreen />} />
            <Route path="/desk" element={<DeskScreen />} />
            <Route path="/previews" element={<PreviewsScreen />} />
            <Route path="/compare" element={<CompareScreen />} />
            <Route path="/explorer" element={<ExplorerScreen />} />
            <Route path="/field" element={<FieldScreen />} />
            <Route path="/audit" element={<AuditScreen />} />
            <Route path="/scout" element={<ScoutScreen />} />
            <Route path="/advanced" element={<AdvancedScreen />} />
            <Route path="/live" element={<LiveScreen />} />
            <Route path="/leagues" element={<LeaguesScreen />} />
          </Routes>
          </Suspense>
          </div>
        </main>
      </SidebarInset>
      <CommandPalette />
    </SidebarProvider>
  )
}

export default App
