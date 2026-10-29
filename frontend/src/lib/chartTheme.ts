import type { ApexOptions } from 'apexcharts'

/** One chart language for the whole app.
 *
 * Every chart shares one base, so a graph looks like part of the same broadcast package by default and a per-chart override is
 * a deliberate act. What the base does:
 * - a line sits on a single-hue fade (opaque at the line, clear at the axis), never a rainbow ramp and never a glow
 * - bars are rounded at the free end; lines end in a round cap, and the last point of a series is marked and labelled
 * - the grid is dashed horizontals only, axes carry no border or ticks, the hover crosshair is a thin dashed rule
 * - tooltips are the app's own panel (see `.apexcharts-tooltip` in index.css)
 * - tabular figures on every axis so numbers line up column to column
 * - motion is a real data-arrival event, disabled under reduced motion
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
      strokeDashArray: 4,
      xaxis: { lines: { show: false } },
      padding: { left: 8, right: 20, top: 8, bottom: 0 },
      ...(overrides.grid ?? {}),
    },
    xaxis: {
      axisBorder: { show: false },
      axisTicks: { show: false },
      crosshairs: { stroke: { color: 'var(--text-faint)', width: 1, dashArray: 3 } },
      tooltip: { enabled: false },
      ...(overrides.xaxis ?? {}),
    },
    markers: { size: 0, strokeWidth: 3, strokeColors: 'var(--panel)', hover: { sizeOffset: 3 }, ...(overrides.markers ?? {}) },
    dataLabels: { enabled: false, ...(overrides.dataLabels ?? {}) },
    legend: { show: false, ...(overrides.legend ?? {}) },
    stroke: { width: 2.5, curve: 'monotoneCubic', lineCap: 'round', ...(overrides.stroke ?? {}) },
    plotOptions: {
      ...(overrides.plotOptions ?? {}),
      bar: { borderRadius: 5, borderRadiusApplication: 'end', columnWidth: '52%', ...(overrides.plotOptions?.bar ?? {}) },
    },
    tooltip: {
      theme: 'light',
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
    xaxis: _xaxis,
    markers: _markers,
    plotOptions: _plotOptions,
    tooltip: _tooltip,
    states: _states,
    ...rest
  } = o
  return rest
}

/** The fade under a line: one hue, opaque at the line and clear at the axis. The line stays the information, the fade is
 * context. `strength` is the opacity at the line. */
export function areaFade(strength = 0.5, reversedAxis = false): ApexOptions['fill'] {
  return {
    type: 'gradient',
    gradient: {
      shade: 'dark',
      type: 'vertical',
      shadeIntensity: 0,
      opacityFrom: reversedAxis ? 0 : strength,
      opacityTo: reversedAxis ? strength : 0,
      stops: [0, 92, 100],
    },
  }
}

/** Rounded bars that thin slightly toward the base. */
export function barFill(): ApexOptions['fill'] {
  return {
    type: 'gradient',
    gradient: { shade: 'dark', type: 'vertical', shadeIntensity: 0, opacityFrom: 1, opacityTo: 0.62, stops: [0, 100] },
  }
}

/** Marks and labels the last point of a series, so a chart ends on the number it is about. */
export function lastPoint(x: string | number, y: number, color: string, text: string): NonNullable<ApexOptions['annotations']> {
  return {
    points: [
      {
        x,
        y,
        marker: { size: 6, fillColor: color, strokeColor: 'var(--panel)', strokeWidth: 3 },
        label: {
          text,
          offsetY: -4,
          offsetX: -14,
          borderWidth: 0,
          borderRadius: 6,
          style: { color: '#0b0e13', background: color, fontWeight: 700, fontSize: '12px', padding: { left: 7, right: 7, top: 3, bottom: 3 } },
        },
      },
    ],
  }
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

export function formatRank(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}m`
  return v >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`
}

/** Overall rank reads better in thousands, and lower is better - the axis
 * has to be reversed or the chart tells the opposite story. */
export const rankAxisLabels = {
  formatter: (v: number) => formatRank(v),
  style: { cssClass: 'tabular' },
}
