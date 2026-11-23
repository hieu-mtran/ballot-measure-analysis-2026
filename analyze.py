"""Analyze 2026 statewide ballot measures against each state's party vote.

Reads data/*.csv and the CivicAPI responses cached by fetch.py, then writes:
  results/measure_results.csv   one row per measure: yes share, outcome, reporting, party-vote comparison
  results/summary.md            the tables quoted in the README
  charts/pass_rates.png         how often measures passed, by how they reached the ballot
  charts/party_gap.png          how far each partisan measure ran ahead of or behind the party vote
"""
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).parent
CACHE = ROOT / 'cache'
RESULTS = ROOT / 'results'
CHARTS = ROOT / 'charts'

# Reference palette (light mode).
SURFACE, INK, INK_2, MUTED, GRID, AXIS = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7'
BLUE, ORANGE = '#2a78d6', '#eb6834'
FULLY_REPORTED = 95.0  # percent reporting below which a result is flagged as incomplete


def load_race(race_id):
    path = CACHE / f'{race_id}.json'
    return json.loads(path.read_text()) if path.exists() else None


def yes_no(race):
    """Yes and No votes for a yes/no measure, or None when the race isn't one."""
    votes = {(c.get('name') or '').strip().lower(): c.get('votes') or 0 for c in race['candidates']}
    yes = next((v for k, v in votes.items() if k.startswith('yes') or k in ('for', 'approve', 'approved')), None)
    no = next((v for k, v in votes.items() if k.startswith('no') or k in ('against', 'reject', 'rejected')), None)
    return (yes, no) if yes is not None and no is not None and yes + no > 0 else None


def two_party(race):
    """Democratic share of the Democratic and Republican vote, only when those two finish first and second."""
    ranked = sorted(race['candidates'], key=lambda c: -(c.get('votes') or 0))
    if len(ranked) < 2 or {ranked[0].get('party'), ranked[1].get('party')} != {'Democratic', 'Republican'}:
        return None
    d = next(c['votes'] for c in ranked[:2] if c['party'] == 'Democratic')
    r = next(c['votes'] for c in ranked[:2] if c['party'] == 'Republican')
    return d, r


def party_vote():
    """Each state's Democratic two-party share: the mean of its Senate and governor races where a Democrat and a
    Republican finished first and second; where there are none, its contested House races combined."""
    races = pd.read_csv(ROOT / 'data' / 'party_races.csv', dtype=str)
    out = {}
    for state, group in races.groupby('state'):
        statewide = []
        house_d = house_r = 0
        for _, row in group.iterrows():
            race = load_race(row.civic_race_id)
            pair = two_party(race) if race else None
            if not pair:
                continue
            if row.office == 'house':
                house_d += pair[0]
                house_r += pair[1]
            else:
                statewide.append(100 * pair[0] / sum(pair))
        if statewide:
            out[state] = (sum(statewide) / len(statewide), 'Senate/governor')
        elif house_d:
            out[state] = (100 * house_d / (house_d + house_r), 'House')
    return out


def build_table():
    measures = pd.read_csv(ROOT / 'data' / 'measures.csv', dtype={'civic_race_id': str}, keep_default_na=False)
    dem = party_vote()
    rows = []
    for m in measures.itertuples():
        race = load_race(m.civic_race_id)
        votes = yes_no(race) if race else None
        if not votes:
            continue
        yes = 100 * votes[0] / sum(votes)
        threshold = 100 * float(m.approval_threshold)
        dem_vote, dem_source = dem.get(m.state, (None, ''))
        dem_side = {'yes': yes, 'no': 100 - yes}.get(m.dem_side)
        rows.append({
            'state': m.state, 'designation': m.designation, 'short_title': m.short_title, 'origin': m.origin,
            'topic': m.topic, 'rules': m.rules, 'dem_side': m.dem_side,
            'yes_pct': round(yes, 1), 'threshold_pct': threshold, 'passed': yes >= threshold,
            'percent_reporting': race.get('percent_reporting'),
            'dem_side_pct': round(dem_side, 1) if dem_side is not None else None,
            'dem_vote_pct': round(dem_vote, 1) if dem_vote is not None else None,
            'dem_vote_source': dem_source,
            'gap_pts': round(dem_side - dem_vote, 1) if dem_side is not None and dem_vote is not None else None,
        })
    table = pd.DataFrame(rows)
    table['incomplete'] = table.percent_reporting.fillna(0) < FULLY_REPORTED
    return table


def shorten(text, limit=46):
    """Cut a title at a word boundary so chart labels never end mid-word."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0].rstrip(',;:') + '…'


def group_label(row):
    if row.rules == 'curb':
        return 'Referred by legislature: curbs on voters' if row.origin == 'legislature' else 'Other curbs'
    if row.origin == 'legislature':
        return 'Referred by legislature: everything else'
    return {'citizens': 'Citizen initiatives', 'referendum': 'Referendums'}.get(row.origin, 'Other')


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def chart_pass_rates(table):
    table = table.assign(group=table.apply(group_label, axis=1))
    order = ['Referred by legislature: everything else', 'Referred by legislature: curbs on voters', 'Citizen initiatives', 'Referendums']
    stats = table.groupby('group').passed.agg(['sum', 'count']).reindex(order).dropna()
    stats['rate'] = 100 * stats['sum'] / stats['count']
    fig, ax = plt.subplots(figsize=(7.5, 3.4), facecolor=SURFACE)
    style(ax)
    colors = [ORANGE if 'curbs' in g else BLUE for g in stats.index]
    ax.barh(range(len(stats)), stats.rate, color=colors, height=0.55)
    for i, (g, s) in enumerate(stats.iterrows()):
        ax.text(s.rate + 1.5, i, f'{s.rate:.0f}%  ({int(s["sum"])} of {int(s["count"])})', va='center', fontsize=9, color=INK_2)
    ax.set_yticks(range(len(stats)), stats.index, color=INK, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel('Share of measures that passed', color=MUTED, fontsize=9)
    fig.suptitle('Voters approved most of what legislatures sent them,\nexcept measures curbing their own power',
                 x=0.02, ha='left', fontsize=11, color=INK, fontweight='bold')
    fig.tight_layout()
    fig.savefig(CHARTS / 'pass_rates.png', dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return stats


def chart_party_gap(table):
    partisan = table.dropna(subset=['gap_pts']).copy()
    partisan['process'] = partisan.rules.isin(['curb', 'protect', 'map'])
    partisan = partisan.sort_values(['process', 'gap_pts'], ascending=[False, True])
    fig, ax = plt.subplots(figsize=(7.5, 0.24 * len(partisan) + 1.4), facecolor=SURFACE)
    style(ax)
    ax.axvline(0, color=AXIS, linewidth=1)
    for i, row in enumerate(partisan.itertuples()):
        color = ORANGE if row.process else BLUE
        face = SURFACE if row.incomplete else color
        ax.plot([0, row.gap_pts], [i, i], color=color, linewidth=2, solid_capstyle='round', alpha=0.35)
        ax.scatter(row.gap_pts, i, s=42, color=face, edgecolors=color, linewidths=1.6, zorder=3)
    labels = [f'{r.state} · {shorten(r.short_title)}' for r in partisan.itertuples()]
    ax.set_yticks(range(len(partisan)), labels, fontsize=8, color=INK_2)
    ax.invert_yaxis()
    ax.set_xlabel('Democratic-aligned side vs. the state\'s Democratic vote (points)',
                  color=MUTED, fontsize=9)
    handles = [plt.Line2D([], [], marker='o', linestyle='', color=ORANGE, label='Rules of the game'),
               plt.Line2D([], [], marker='o', linestyle='', color=BLUE, label='Policy'),
               plt.Line2D([], [], marker='o', linestyle='', color=MUTED, markerfacecolor=SURFACE, label='Under 95% reporting')]
    fig.legend(handles=handles, loc='upper left', bbox_to_anchor=(0.015, 0.975), ncol=3, fontsize=8, frameon=False,
               labelcolor=INK_2, handletextpad=0.3, columnspacing=1.2)
    fig.suptitle('Where ballot measures ran ahead of or behind the party vote', x=0.02, ha='left',
                 fontsize=11, color=INK, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    fig.savefig(CHARTS / 'party_gap.png', dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return partisan


def main():
    RESULTS.mkdir(exist_ok=True)
    CHARTS.mkdir(exist_ok=True)
    table = build_table()
    table.to_csv(RESULTS / 'measure_results.csv', index=False)
    rates = chart_pass_rates(table)
    partisan = chart_party_gap(table)
    by_topic = (partisan.groupby('topic').gap_pts.agg(['mean', 'count']).round(1)
                .sort_values('mean', ascending=False))
    lines = ['# Summary tables', '', f'{len(table)} measures with yes/no results; '
             f'{int(table.incomplete.sum())} under {FULLY_REPORTED:.0f}% reporting.', '',
             '## Pass rates by how the measure reached the ballot', '', rates[['sum', 'count', 'rate']]
             .rename(columns={'sum': 'passed', 'count': 'measures', 'rate': 'pass rate (%)'}).round(0).to_markdown(), '',
             '## Gap from the party vote, by topic (Democratic-aligned side minus Democratic share, points)', '',
             by_topic.rename(columns={'mean': 'mean gap', 'count': 'measures'}).to_markdown(), '',
             '## Rules-of-the-game measures', '',
             partisan[partisan.process][['state', 'designation', 'short_title', 'yes_pct', 'passed', 'gap_pts', 'percent_reporting']]
             .to_markdown(index=False)]
    (RESULTS / 'summary.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
