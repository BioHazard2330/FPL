import type { CSSProperties } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppSidebar } from '@/components/shell/AppSidebar'
import { ContextHeader } from '@/components/shell/ContextHeader'
import { MatchdayBar } from '@/components/shell/MatchdayBar'
import { MatchweekScreen } from '@/screens/Matchweek/MatchweekScreen'
import { ClubScreen } from '@/screens/Profile/ClubScreen'
import { MatchScreen } from '@/screens/Profile/MatchScreen'
import { PlayerScreen } from '@/screens/Profile/PlayerScreen'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { CommandScreen } from '@/screens/Command/CommandScreen'
import { MyTeamScreen } from '@/screens/MyTeam/MyTeamScreen'
import { PlanScreen } from '@/screens/Plan/PlanScreen'
import { FootballScreen } from '@/screens/Football/FootballScreen'
import { ScoutScreen } from '@/screens/Scout/ScoutScreen'
import { AdvancedScreen } from '@/screens/Advanced/AdvancedScreen'
import { LiveScreen } from '@/screens/Live/LiveScreen'
import { CommandPalette } from '@/components/shell/CommandPalette'

function App() {
  return (
    <SidebarProvider style={{ '--sidebar-width': '13rem' } as CSSProperties}>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <ContextHeader />
        <MatchdayBar />
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<CommandScreen />} />
            <Route path="/my-team" element={<MyTeamScreen />} />
            <Route path="/plan" element={<PlanScreen />} />
            <Route path="/matchweek" element={<MatchweekScreen />} />
            <Route path="/club/:id" element={<ClubScreen />} />
            <Route path="/player/:id" element={<PlayerScreen />} />
            <Route path="/match/:id" element={<MatchScreen />} />
            <Route path="/football" element={<FootballScreen />} />
            <Route path="/scout" element={<ScoutScreen />} />
            <Route path="/advanced" element={<AdvancedScreen />} />
            <Route path="/live" element={<LiveScreen />} />
          </Routes>
        </main>
      </SidebarInset>
      <CommandPalette />
    </SidebarProvider>
  )
}

export default App
