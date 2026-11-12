import { money, money0, moneyCompact, percent } from '../core/format';
import { Holding } from '../core/models';
import { ChartTokens } from './chart';

/** Horizontal bars, largest first, labeled with value and share (shared with the dashboard). */
export function topHoldingsOption(top: Holding[], t: ChartTokens) {
  return {
    grid: { left: 8, right: 120, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'item',
      backgroundColor: t.surface,
      borderColor: t.rule,
      textStyle: { color: t.ink },
      formatter: (p: { dataIndex: number }) => {
        const h = top[p.dataIndex];
        return `<strong>${h.description}</strong><br/>${money(h.market_value)} · ${percent(h.pct_of_portfolio)} of portfolio`;
      },
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: t.muted, formatter: (v: number) => moneyCompact(v) },
      splitLine: { lineStyle: { color: t.grid } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: top.map((h) => h.symbol),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.rule } },
      axisLabel: {
        formatter: (_: string, i: number) =>
          `{name|${shortName(top[i].description)}} {sym|${top[i].symbol}}`,
        rich: { name: { color: t.ink, fontWeight: 500 }, sym: { color: t.muted } },
      },
    },
    series: [
      {
        type: 'bar',
        data: top.map((h) => h.market_value),
        barMaxWidth: 18,
        itemStyle: { color: t.pos, borderRadius: [0, 4, 4, 0] },
        label: {
          show: true,
          position: 'right',
          color: t.ink,
          formatter: (p: { dataIndex: number }) =>
            `${money0(top[p.dataIndex].market_value)}  ${percent(top[p.dataIndex].pct_of_portfolio)}`,
        },
      },
    ],
  };
}

/** "Microsoft Corp." -> "Microsoft"; keeps axis labels short. The full name is in the tooltip and table. */
export function shortName(description: string): string {
  const cut = description.replace(
    /,? (& Co\.|Inc\.|Corp\.|Co\.|plc|Corporation|Company|Class [A-Z]).*$/,
    '',
  );
  return cut.length > 22 ? cut.slice(0, 21) + '…' : cut;
}
