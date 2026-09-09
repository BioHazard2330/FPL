import type { ApexOptions } from 'apexcharts'

/** One chart language for the whole app.
 *
 * Before this, every chart carried its own inline ApexCharts config: three
 * on Live, one on Plan, each independently re-declaring grid colour, font
 * colour, toolbar, tooltip theme and stroke width. They drifted (one used a
 * two-stop gradient fill, which DESIGN.md's own no-gradient rule forbids;
 * one had fractional gameweek ticks). A shared base makes a chart look like
 * part of the same broadcast package by default, and makes a per-chart
 * override a deliberate act rather than an accident.
 *
 * Rules encoded here, all from DESIGN.md:
 * - flat fills, no multi-stop gradients, no glow, no drop shadows
 * - square corners on every bar (`borderRadius: 0`)
 * - the palette's semantic roles, never a decorative colour ramp
 * - tabular figures on axis labels so numbers line up column-to-column
 * - animation is a real data-arrival event, disabled under reduced motion
 */

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

export const CHART_COLORS = {
  primary: 'var(--pitch-green)',
  secondary: 'var(--broadcast-blue)',
  accent: 'var(--broadcast-gold)',
  danger: 'var(--alert-red)',
  muted: 'var(--divider)',
} as const

/** The shared base. Spread it, then override only what a chart genuinely
 * needs to say something different. */
export function baseChart(overrides: ApexOptions = {}): ApexOptions {
  const reduced = prefersReducedMotion()
  return {
    chart: {
      toolbar: { show: false },
      zoom: { enabled: false },
      background: 'transparent',
      foreColor: 'var(--text-muted)',
      fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
      // Motion only on first paint of real data, and only ever once - a
      // chart that re-animates on every 10s poll is a distraction, not
      // information.
      animations: {
        enabled: !reduced,
        speed: 500,
        animateGradually: { enabled: false },
        dynamicAnimation: { enabled: !reduced, speed: 300 },
      },
      ...(overrides.chart ?? {}),
    },
    grid: {
      borderColor: 'var(--divider)',
      strokeDashArray: 0,
      xaxis: { lines: { show: false } },
      padding: { left: 8, right: 16, top: 0, bottom: 0 },
      ...(overrides.grid ?? {}),
    },
    dataLabels: { enabled: false, ...(overrides.dataLabels ?? {}) },
    legend: { show: false, ...(overrides.legend ?? {}) },
    stroke: { width: 3, curve: 'straight', lineCap: 'butt', ...(overrides.stroke ?? {}) },
    plotOptions: {
      ...(overrides.plotOptions ?? {}),
      bar: { borderRadius: 0, columnWidth: '45%', ...(overrides.plotOptions?.bar ?? {}) },
    },
    tooltip: {
      theme: 'dark',
      style: { fontFamily: "'IBM Plex Sans', system-ui, sans-serif" },
      ...(overrides.tooltip ?? {}),
    },
    states: {
      hover: { filter: { type: 'lighten' } },
      active: { filter: { type: 'none' } },
      ...(overrides.states ?? {}),
    },
    ...stripHandled(overrides),
  }
}

/** The keys `baseChart` merges by hand above. Stripping them here stops a
 * caller's partial override from clobbering the merged result via the final
 * spread. */
function stripHandled(o: ApexOptions): ApexOptions {
  const {
    chart: _chart,
    grid: _grid,
    dataLabels: _dataLabels,
    legend: _legend,
    stroke: _stroke,
    plotOptions: _plotOptions,
    tooltip: _tooltip,
    states: _states,
    ...rest
  } = o
  return rest
}

/** A single flat area wash under a line - the one fill this system allows.
 * Deliberately NOT a two-stop gradient: it is one colour at one low opacity,
 * so the line stays the information and the fill stays context. */
export function flatAreaFill(opacity = 0.14): ApexOptions['fill'] {
  return { type: 'solid', opacity }
}

/** Gameweeks are integers. Every gameweek axis in this app formats through
 * here so no chart can ever again render a tick reading "GW6.8". */
export const gwAxisLabels = {
  formatter: (v: string | number) => `GW${Math.round(Number(v))}`,
  style: { fontFamily: "'IBM Plex Sans', system-ui, sans-serif", cssClass: 'tabular' },
}

export const intAxisLabels = {
  formatter: (v: number) => Math.round(v).toString(),
  style: { cssClass: 'tabular' },
}

/** Overall rank reads better in thousands, and lower is better - the axis
 * has to be reversed or the chart tells the opposite story. */
export const rankAxisLabels = {
  formatter: (v: number) => (v >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`),
  style: { cssClass: 'tabular' },
}
