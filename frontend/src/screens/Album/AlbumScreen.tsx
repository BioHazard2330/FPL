import { Link } from 'react-router-dom'
import { Masthead } from '@/components/shell/Masthead'
import { Skel, ScreenError } from '@/components/shell/ScreenStates'
import { HeroPhoto } from '@/components/ui/HeroPhoto'
import { crestUrl, getJson } from '@/lib/api'
import { clubColors } from '@/lib/clubs'
import { useFetch } from '@/lib/useFetch'

/** THE SQUAD ALBUM - the fifteen as printed stickers: club colours and crest, the cut-out, the season's real numbers, the
 * scouting profile with his best and worst measure, the football read's verdict and the lines behind it (marked by whether
 * that kind of evidence carries from match to match), what the plan intends for him, and how much of the top ten
 * thousand owns him. A sticker is a judgement on one page; every part of it is a stored reading. */

interface Sticker {
  player_id: number; name: string; full_name: string; photo_code: number | null; team_name: string; team_short: string; team_code: number
  position: string; price: number; status: string; news: string | null
  season: { points: number | null; minutes: number | null; goals: number | null; assists: number | null; bonus: number | null; xg: number | null; xa: number | null; starts: number | null }
  xp: number | null; top10k_eo: number | null
  verdict: { label: string; score: number; text: string } | null
  lines: { topic: string; weight: string; lean: number; text: string }[]
  profile: string[]
  best: { label: string; display: string; percentile: number }[]
  worst: { label: string; display: string; percentile: number }[]
  fate: { kind: 'sell' | 'captain' | 'bench' | 'keep'; when: string | null; for?: string } | null
  my_eye?: { event: number; rating: number; tags: string[]; note: string | null; label: string } | null
}
interface AlbumPayload { status: string; event: number | null; stickers: Sticker[] }

const STAMP: Record<string, string> = {
  'backs him': 'bg-pitch-green text-pitch-green-ink', mixed: 'bg-broadcast-gold text-ink', 'against him': 'bg-alert-red text-alert-red-ink',
}
const WEIGHT: Record<string, string> = { carries: 'text-pitch-green', noise: 'text-text-faint line-through decoration-1', context: 'text-text-muted' }
const ordinal = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] ?? 'th'}`
const POS_NAME: Record<string, string> = { GKP: 'Goalkeepers', DEF: 'Defenders', MID: 'Midfielders', FWD: 'Forwards' }

function Fate({ f }: { f: Sticker['fate'] }) {
  if (!f || f.kind === 'keep') return null
  const tone = f.kind === 'sell' ? 'bg-alert-red text-alert-red-ink' : f.kind === 'captain' ? 'bg-broadcast-gold text-ink' : 'bg-raised text-text'
  const text = f.kind === 'sell' ? `sell ${f.when}${f.for ? ` → ${f.for}` : ''}` : f.kind === 'captain' ? `captain ${f.when}` : `bench ${f.when}`
  return <div className={`absolute -right-2 top-24 z-20 rotate-[4deg] border-2 border-ink px-2 py-0.5 font-display text-[13px] font-black uppercase shadow-[3px_3px_0_var(--ink)] ${tone}`}>{text}</div>
}

function Card({ s, n }: { s: Sticker; n: number }) {
  const club = clubColors(s.team_code)
  const crest = crestUrl(s.team_code)
  const flagged = s.status !== 'a'
  return (
    <div className="relative w-[17rem] shrink-0">
      <Fate f={s.fate} />
      <Link to={`/player/${s.player_id}`} className="block border-[3px] border-ink bg-paper shadow-[6px_6px_0_var(--ink)] transition-transform hover:-translate-y-1 hover:rotate-[-0.5deg]">
        <div className="relative h-[13.5rem] overflow-hidden" style={{ background: `linear-gradient(150deg, ${club.primary} 0%, color-mix(in srgb, ${club.primary} 65%, #17130e) 100%)` }}>
          <div className="absolute inset-0 opacity-30 [background-image:radial-gradient(rgba(23,19,14,0.55)_1px,transparent_1.5px)] [background-size:5px_5px]" />
          {crest && <img src={crest} alt="" className="absolute -right-8 -top-6 size-40 opacity-25 mix-blend-multiply" />}
          <div className="absolute left-0 top-0 z-10 flex items-center gap-1.5 bg-ink px-2 py-1">
            <span className="font-display text-[15px] font-black text-paper">{String(n).padStart(2, '0')}</span>
            <span className="font-display text-[13px] font-black uppercase text-spot">{s.position}</span>
          </div>
          {crest && <img src={crest} alt="" className="absolute right-2 top-2 z-10 size-9 drop-shadow-[2px_2px_0_rgba(23,19,14,0.5)]" />}
          <HeroPhoto code={s.photo_code} teamCode={s.team_code} isGkp={s.position === 'GKP'} className="absolute bottom-0 left-1/2 h-[12.5rem] w-[12.5rem] -translate-x-1/2" />
          {s.verdict && (
            <div className={`absolute bottom-3 left-2 z-10 rotate-[-6deg] border-2 border-ink px-2 py-0.5 font-display text-[14px] font-black uppercase shadow-[2px_2px_0_var(--ink)] ${STAMP[s.verdict.label] ?? 'bg-paper text-ink'}`} title={s.verdict.text}>
              {s.verdict.label}
            </div>
          )}
          {flagged && <div className="absolute bottom-3 right-2 z-10 bg-alert-red px-1.5 font-display text-[12px] font-black uppercase text-paper" title={s.news ?? ''}>flagged</div>}
          {s.my_eye && (
            <div className={`absolute right-2 top-12 z-10 rotate-[5deg] border-2 border-ink px-1.5 font-display text-[12px] font-black uppercase shadow-[2px_2px_0_var(--ink)] ${s.my_eye.rating > 0 ? 'bg-pitch-green text-paper' : s.my_eye.rating < 0 ? 'bg-alert-red text-paper' : 'bg-paper text-ink'}`}
              title={[s.my_eye.tags.join(', '), s.my_eye.note].filter(Boolean).join(' · ')}>
              your eye: {s.my_eye.label}
            </div>
          )}
        </div>
        <div className="border-y-[3px] border-ink bg-ink px-3 py-1.5">
          <div className="font-display text-[1.7rem] font-black uppercase leading-none text-paper">{s.name}</div>
          <div className="mt-0.5 flex justify-between text-[11px] text-paper/70"><span>{s.team_name}</span><span>£{s.price.toFixed(1)}m</span></div>
        </div>
        <div className="grid grid-cols-4 divide-x-2 divide-ink border-b-2 border-ink text-center">
          {[
            ['pts', s.season.points ?? 0], ['xP', s.xp !== null ? s.xp.toFixed(1) : '—'],
            ['xG+xA', ((s.season.xg ?? 0) + (s.season.xa ?? 0)).toFixed(1)], ['top 10k', s.top10k_eo !== null ? `${Math.round(Math.min(s.top10k_eo, 1) * 100)}%` : '—'],
          ].map(([k, v]) => (
            <div key={k as string} className="py-1">
              <div className="tabular font-display text-xl font-black leading-none text-text">{v}</div>
              <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-text-faint">{k}</div>
            </div>
          ))}
        </div>
        <div className="space-y-1.5 px-3 py-2.5">
          {s.profile.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {s.profile.slice(0, 2).map((p) => <span key={p} className="border border-ink bg-raised px-1.5 text-[11px] font-semibold text-text">{p}</span>)}
            </div>
          )}
          {(s.best.length > 0 || s.worst.length > 0) && (
            <div className="text-[11.5px] leading-snug text-text-muted">
              {s.best.map((m) => <span key={m.label} className="mr-2"><span className="font-semibold text-pitch-green">{ordinal(m.percentile)}</span> {m.label.toLowerCase()}</span>)}
              {s.worst.map((m) => <span key={m.label}><span className="font-semibold text-alert-red">{ordinal(m.percentile)}</span> {m.label.toLowerCase()}</span>)}
            </div>
          )}
          {s.lines.slice(0, 2).map((l) => (
            <div key={l.topic} className="text-[11.5px] leading-snug">
              <span className={`font-display text-[12px] font-black uppercase ${l.lean > 0 ? 'text-pitch-green' : l.lean < 0 ? 'text-alert-red' : 'text-text'}`}>{l.topic}</span>{' '}
              <span className={WEIGHT[l.weight] ?? 'text-text-muted'}>{l.text.split('. ')[0].replace(/\.$/, '')}.</span>
            </div>
          ))}
        </div>
      </Link>
    </div>
  )
}

export function AlbumScreen() {
  const state = useFetch(() => getJson<AlbumPayload>('/api/album'), [])
  let n = 0
  return (
    <div className="data-in pb-16">
      <Masthead right={state.status === 'ready' && state.data.event ? <span>GW{state.data.event} · fifteen stickers</span> : undefined} />
      {state.status === 'loading' && <div className="animate-pulse px-10 py-8"><Skel className="h-96 w-full" /></div>}
      {state.status === 'error' && <ScreenError title="The album is unavailable" description="The squad could not be read." message={state.error.message} />}
      {state.status === 'ready' && state.data.status === 'ok' && (
        <>
          <section className="relative overflow-hidden !bg-ink px-10 py-8 text-paper">
            <div className="absolute inset-0 opacity-20 [background-image:radial-gradient(rgba(246,240,226,0.4)_1px,transparent_1.5px)] [background-size:7px_7px]" />
            <div className="relative flex flex-wrap items-end justify-between gap-6">
              <div>
                <div className="voice text-xl text-paper/70">the official sticker album of one squad · 2026/27</div>
                <div className="font-display text-[5.5rem] font-black uppercase leading-[0.85] [text-shadow:5px_5px_0_var(--spot)]">The squad album</div>
              </div>
              <div className="max-w-md text-[13.5px] leading-relaxed text-paper/80">
                Every sticker is a judgement: the stamp is the football read's verdict on him, the ribbon is what the plan intends,
                and the lines below say which evidence <span className="font-semibold text-[#7fe0a6]">carries</span> from match to match and which is{' '}
                <span className="line-through">noise</span>.
              </div>
            </div>
          </section>
          {['GKP', 'DEF', 'MID', 'FWD'].map((pos) => {
            const group = state.data.stickers.filter((s) => s.position === pos)
            if (!group.length) return null
            return (
              <section key={pos} className="px-10 pb-9 pt-7">
                <h2 className="font-display text-text">{POS_NAME[pos]}</h2>
                <div className="mt-5 flex flex-wrap gap-8">{group.map((s) => <Card key={s.player_id} s={s} n={++n} />)}</div>
              </section>
            )
          })}
        </>
      )}
    </div>
  )
}
