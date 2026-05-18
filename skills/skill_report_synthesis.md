# Skill: Report Synthesis
**File**: `skills/skill_report_synthesis.md`
**Used by**: `agents/research_graph.py`

## Purpose
How to transform raw multi-source research data into a structured
Believe A&R signing recommendation report.

## Required report sections (in order)

1. **Executive summary** — recommendation + top 3 reasons + next step
2. **Artist overview** — genre, origin, career stage, key releases
3. **Streaming analysis** — listeners, growth, markets, audio fit
4. **Press & media analysis** — article count, outlet quality, sentiment
5. **Digital presence** — YouTube metrics, upload cadence
6. **Roster comparison** — top 3 Believe matches with outcomes
7. **Risk factors** — 2-4 specific risks
8. **Recommendation** — SIGN/WATCH + label tier + next step
9. **Data sources & confidence** — what was available, what was missing

## Quality rules
- Cite exact figures — never vague language like "growing quickly"
- Note missing data explicitly — never fabricate
- Write for an A&R manager — explain what numbers mean
- Always include a label tier recommendation (TuneCore vs Premium)
- Risks must be artist-specific — not generic

## Label tier logic
| Condition | Tier |
|-----------|------|
| < 500K listeners, strong DIY | TuneCore |
| > 500K listeners OR 3+ tier-1 press | Premium Solutions |
| > 1M listeners | Premium Solutions (mandatory) |

## Claude synthesis prompt

You are an A&R Intelligence Agent for Believe.
Research data:
SPOTIFY: {spotify_data}
NEWS: {news_data}
YOUTUBE: {youtube_data}
ROSTER MATCHES: {roster_matches}
DATA GAPS: {errors}
Write a complete A&R signing report following the required sections.
Cite exact figures. Choose TuneCore or Premium Solutions and justify it.
Write for an experienced A&R manager.

## Confidence levels
- **High** — all 4 sources available
- **Medium** — 2-3 sources available
- **Low** — only 1 source available, escalate to WATCH