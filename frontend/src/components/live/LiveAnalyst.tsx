import { fetchLiveStory } from '@/lib/api'
import { useFetch } from '@/lib/useFetch'
import { DeservedResult, Findings } from '@/components/match/AnalystPanels'
import type { StorySub } from '@/lib/types'

/** THE LIVE ANALYST - this match, read the way a finished one is.
 *
 * The shots and goals so far, replayed: the result the chances deserve if the
 * match were played again from them, what each side has created while ahead,
 * level and behind, and the substitutions read against the score. A starter
 * taken off before minute 36 is called a probable injury, at the rate the stored
 * matches give for that minute (every one this season was). Provisional by
 * construction and recomputed every twenty seconds; nothing here is stored. */

function SuspectStrip({ subs, names }: { subs: StorySub[]; names: { home: string; away: string } }) {
  const flagged = subs.filter((s) => s.kind === 'INJURY_SUSPECT')
  if (flagged.length === 0) return null
  return (
    <div className="mb-4 space-y-1">
      {flagged.map((s, i) => (
        <div key={i} className="border-l-4 border-alert-red bg-alert-red/10 px-3 py-2 text-sm text-text">
          <span className="mr-2 text-[12px] font-bold text-alert-red">probable injury</span>
          <span className="font-bold">{s.off}</span> off at minute {s.minute} for {s.on} ({s.side === 'home' ? names.home : names.away}). <span className="text-text-muted">{s.note}.</span>
        </div>
      ))}
    </div>
  )
}

export function LiveAnalyst({ matchId, homeShort, awayShort }: { matchId: number; homeShort: string; awayShort: string }) {
  const state = useFetch(() => fetchLiveStory(matchId), [matchId], 20000)
  if (state.status !== 'ready') return null
  const { story } = state.data
  if (story.length < 15 && story.shots.length < 3 && !story.subs.some((x) => x.kind === 'INJURY_SUSPECT')) return null
  const names = { home: homeShort, away: awayShort }
  const prof = story.state_profile
  return (
    <div className="border-t border-divider px-6 py-5">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="text-[12px] font-bold text-pitch-green">Reading the match so far, minute {story.length}</div>
        <div className="text-[12px] text-text-faint">{story.shots.length} shots so far; this reading is provisional</div>
      </div>
      <SuspectStrip subs={story.subs} names={names} />
      <DeservedResult story={story} names={names} />
      {prof && (
        <div className="mt-6 grid grid-cols-2 gap-6 text-sm">
          {(['home', 'away'] as const).map((side) => {
            const p = prof[side]
            return (
              <div key={side}>
                <div className={`text-[12px] font-bold ${side === 'home' ? 'text-pitch-green' : 'text-broadcast-blue'}`}>{names[side]}: chances by score</div>
                <div className="tabular mt-1 text-text-muted">
                  ahead for {Math.round(p.leading.minutes)}&apos;, {p.leading.xg_for.toFixed(2)} xG<br />
                  level for {Math.round(p.level.minutes)}&apos;, {p.level.xg_for.toFixed(2)} xG<br />
                  behind for {Math.round(p.trailing.minutes)}&apos;, {p.trailing.xg_for.toFixed(2)} xG
                </div>
              </div>
            )
          })}
        </div>
      )}
      {story.findings.length > 0 && (
        <div className="mt-5">
          <Findings findings={story.findings} limit={3} />
        </div>
      )}
    </div>
  )
}
