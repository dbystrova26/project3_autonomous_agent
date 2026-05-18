# Skill: News & Press Analysis
**File**: `skills/skill_news_analysis.md`
**Used by**: `agents/triage_chain.py`, `agents/research_graph.py`

## Purpose
How to fetch, classify, and score press coverage for A&R evaluation
at Believe. Press traction is one of the strongest signals that an
artist is breaking through — editorial coverage cannot be bought
at scale the way social media followers can.

## API setup
- **Library**: newsapi-python
- **Auth**: NEWSAPI_KEY in .env
- **Free tier**: 100 requests/day
- **Cache**: results stored per artist for 24 hours to preserve quota

## What we fetch
Query: '"artist name" music', last 30 days, English, sorted by date.
Returns: article list with title, source name, published date, URL.

## Outlet tier classification

### Tier-1 outlets (5 pts each)
Editorial publications with global reach and full independence.
Coverage here cannot be paid for — it is genuine critical interest.
NME, Pitchfork, Resident Advisor, Billboard, Rolling Stone,
Mixmag, DJ Mag, The Guardian, FACT Magazine, DIY Magazine,
The Line of Best Fit, Kerrang, Les Inrockuptibles,
Musikexpress, Noisey (VICE Music)

### Tier-2 outlets (2 pts each)
Regional music publications and large music blogs.
Clash Music, Gigwise, The 405, Consequence of Sound,
Stereogum, HipHopDX, Complex, Afrobeats Intelligence,
Data Transmission, XLR8R, Dummy Mag, Loud and Quiet

### Blog / community (0.5 pts each)
Artist blogs, Substack newsletters, fan sites, uncategorised sources.

## Scoring formula
raw_score = (tier1_count x 5.0) + (tier2_count x 2.0) + (blog_count x 0.5)
recency_bonus = recency_score x 5.0
final_score = min(25, raw_score + recency_bonus)
Maximum press score: 25 points

## Recency weighting
- Articles published in last 7 days: weight x 2
- Articles published 8-30 days ago: weight x 1
- Recent coverage matters more — an NME article from yesterday
  is worth more than one from 28 days ago

## Genre context adjustments
| Genre | Adjustment |
|-------|-----------|
| Electronic / techno | Resident Advisor = strongest possible signal. Fewer total articles expected — do not penalise low count |
| Afrobeats / African | Nigerian specialist outlets (Pulse Nigeria, NotJustOk) elevated to tier-2 |
| Metal | Metal Hammer and Blabbermouth = tier-1 alongside Kerrang |
| Latin | Billboard Latin and Rolling Stone en Espanol = tier-1 |
| French rap | Booska-P elevated to tier-2. Lower volume expected vs UK/US |

## Sentiment scoring
Scan headline text for keywords — rough proxy only.

Positive keywords (+0.15 each):
breakthrough, essential, one to watch, standout, powerful,
acclaimed, stunning, brilliant, must-hear, rising

Negative keywords (-0.20 each):
disappointing, fails, underwhelming, controversy,
plagiarism, lawsuit, cancelled

Sentiment score capped at +1.0 / -1.0.
Report as: Strongly positive / Positive / Neutral / Mixed / Negative

## Decision thresholds
| Press score | Signal strength |
|------------|----------------|
| 20-25 | Exceptional — multiple tier-1 outlets |
| 10-19 | Strong — mix of tier-1 and tier-2 |
| 5-9 | Moderate — tier-2 and blog coverage |
| 1-4 | Weak — blogs only |
| 0 | No coverage found |

## Important interpretation notes
- Absence of press is not always negative — many afrobeats and
  electronic artists build huge streaming audiences before press
  catches up. Weight genre context heavily.
- A single Resident Advisor review outweighs 20 blog posts
- NME ones to watch features are unsolicited editorial —
  one of the strongest possible signals at emerging artist stage
- Blog coverage from genre-specialist sites is more meaningful
  than general lifestyle blogs

## Error handling
| Error | Action |
|-------|--------|
| 429 rate limit | Wait 60s, retry once |
| 0 results | Return empty summary, note in report — do not score as zero |
| API timeout | Retry max 3 times with backoff |
| Daily quota exceeded | Return cached result if available, else flag news_unavailable |

## Example output
{
  "article_count": 18,
  "tier1_count": 3,
  "tier2_count": 7,
  "blog_count": 8,
  "top_headlines": [
    "NME: Nova Eclipse named one of 10 UK artists to watch",
    "DIY Magazine: Nova Eclipse is ready to break through"
  ],
  "sources": ["NME", "DIY Magazine", "Clash Music"],
  "recency_score": 0.85,
  "sentiment_score": 0.74,
  "press_score": 22
}