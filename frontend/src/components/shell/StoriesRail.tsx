import { useState } from 'react'
import { Play } from 'lucide-react'
import { relativeTime } from '@/lib/time'
import type { Story } from '@/lib/types'

/** IN THE NEWS - what publishers have said about this player or club: articles
 * and community posts as linked headlines, videos as click-to-play embeds.
 * Nothing loads from YouTube until a video is clicked. The stories are linked
 * by matching names in the text, which is best-effort: an item can mention the
 * name without being about the person, and the headline is always shown so that
 * is easy to see. */
export function StoriesRail({ stories, subject }: { stories: Story[] | undefined; subject: string }) {
  const [playing, setPlaying] = useState<string | null>(null)
  if (!stories || stories.length === 0) return null
  const videos = stories.filter((s) => s.kind === 'video').slice(0, 3)
  const rest = stories.filter((s) => s.kind !== 'video').slice(0, 8)
  return (
    <div className="border-t-2 border-divider px-10 py-8">
      <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.1em] text-text-faint">In the news</div>
      <p className="mb-4 text-xs text-text-muted">Stories that name {subject}, newest first. Matched on names in the text.</p>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-10">
        <div>
          {rest.map((s) => (
            <a key={s.id} href={s.link} target="_blank" rel="noreferrer" className="flex gap-3 border-b border-divider py-2.5">
              {s.image ? (
                <img src={s.image} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-14 w-24 shrink-0 object-cover" />
              ) : (
                <div className="flex h-14 w-24 shrink-0 items-end bg-raised p-1.5 font-display text-xs font-bold uppercase leading-none text-text-faint">{s.kind === 'post' ? 'r/FantasyPL' : s.source}</div>
              )}
              <div className="min-w-0">
                <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">{s.source} · {relativeTime(s.published_at) ?? ''}</div>
                <div className="text-sm font-semibold leading-snug text-text hover:text-pitch-green">{s.title}</div>
              </div>
            </a>
          ))}
        </div>
        <div className="space-y-5">
          {videos.map((v) => (
            <div key={v.id}>
              <div className="relative aspect-video w-full bg-raised">
                {playing === v.id && v.video_id ? (
                  <iframe
                    className="absolute inset-0 h-full w-full"
                    src={`https://www.youtube-nocookie.com/embed/${v.video_id}?autoplay=1&rel=0`}
                    title={v.title}
                    allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                    allowFullScreen
                  />
                ) : (
                  <button type="button" onClick={() => setPlaying(v.id)} className="group absolute inset-0 block h-full w-full" aria-label={`Play ${v.title}`}>
                    {v.image && <img src={v.image} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-full w-full object-cover" />}
                    <span className="absolute left-3 top-3 flex h-9 w-9 items-center justify-center bg-void text-text group-hover:bg-pitch-green group-hover:text-pitch-green-ink">
                      <Play size={16} fill="currentColor" />
                    </span>
                  </button>
                )}
              </div>
              <div className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-text-faint">{v.source} · {relativeTime(v.published_at) ?? ''}</div>
              <div className="text-sm font-semibold leading-snug text-text">{v.title}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
