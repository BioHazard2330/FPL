import { lazy, Suspense, useState } from 'react'
import type { MatchStory } from '@/lib/types'
import { MatchReplay } from './MatchReplay'
import { DeservedResult, Findings, GameState, SituationMix, Substitutions } from './AnalystPanels'

const Shots3D = lazy(() => import('./Shots3D').then((m) => ({ default: m.Shots3D })))

/** THE ANALYST'S READ - what this match was, from its own shots.
 *
 * Built in `models/match_analyst.py` from stored shots, goals, substitutions
 * and FPL's status changes. No language model wrote any of it: every sentence
 * is a number the analyst measured, and each finding that rests on a
 * repeatable signal carries how well that signal has carried from one match to
 * the next this season and across every stored season. */
export function MatchAnalyst({ story, homeShort, awayShort, homeId }: { story: MatchStory; homeShort: string; awayShort: string; homeId: number }) {
  const names = { home: homeShort, away: awayShort }
  const [air, setAir] = useState(false)
  const band = 'border-b border-divider px-10 py-8'
  const eyebrow = 'mb-4 text-[13px] font-medium text-text-faint'
  return (
    <>
      <div className={band}>
        <div className="mb-2 flex items-baseline justify-between gap-4">
          <div className="text-[13px] font-bold text-pitch-green">The analyst&rsquo;s read</div>
          <div className="text-[12px] text-text-faint">{story.version}</div>
        </div>
        <h2 className="max-w-5xl font-display text-[1.75rem] font-semibold leading-tight text-text">{story.headline}</h2>
        <div className="mt-6">
          <DeservedResult story={story} names={names} />
        </div>
      </div>

      <div className={band}>
        <div className={eyebrow}>The replay</div>
        <MatchReplay story={story} homeShort={homeShort} awayShort={awayShort} homeId={homeId} />
      </div>

      <div className={band}>
        <div className="mb-4 flex items-center justify-between gap-4">
          <div className="text-[13px] font-medium text-text-faint">Every shot in the air · {story.shots.length} shots, struck to where each crossed the goal line</div>
          {!air && (
            <button type="button" onClick={() => setAir(true)} className="border-2 border-ink bg-ink px-3 py-1 font-display text-[13px] font-black uppercase tracking-[0.06em] text-paper shadow-[3px_3px_0_var(--spot)] hover:bg-spot hover:text-ink">
              Play them under the lights 3D
            </button>
          )}
        </div>
        {air && (
          <Suspense fallback={<div className="grid h-[520px] place-items-center bg-[#0a0d14] font-display text-paper">Switching on the floodlights</div>}>
            <Shots3D shots={story.shots} homeShort={homeShort} awayShort={awayShort} />
          </Suspense>
        )}
      </div>

      <div className="grid grid-cols-1 gap-px border-b border-divider bg-divider lg:grid-cols-2">
        <div className="bg-void px-10 py-8">
          <div className={eyebrow}>Chances by game state</div>
          <GameState story={story} names={names} />
        </div>
        <div className="bg-void px-10 py-8">
          <div className={eyebrow}>Where the chances came from</div>
          <SituationMix story={story} names={names} />
        </div>
      </div>

      {story.subs.length > 0 && (
        <div className={band}>
          <div className={eyebrow}>Substitutions, read against the score</div>
          <Substitutions subs={story.subs} names={names} />
        </div>
      )}

      <div className={band}>
        <div className={eyebrow}>Findings</div>
        <Findings findings={story.findings} />
        <p className="mt-4 max-w-4xl text-[12px] leading-relaxed text-text-faint">{story.uncertainties}</p>
      </div>
    </>
  )
}
