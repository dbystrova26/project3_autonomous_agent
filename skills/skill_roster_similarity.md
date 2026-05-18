# Skill: Roster Similarity Search
**File**: `skills/skill_roster_similarity.md`
**Used by**: `agents/research_graph.py`

## Purpose
How to query Believe's simulated artist roster in Pinecone to find
comparable signed artists and use their outcomes to inform recommendations.

## Pinecone index
- **Index name**: `believe-roster`
- **Dimensions**: 1536 (text-embedding-3-small)
- **Metric**: cosine
- **Vector count**: 25 artist profiles

## Query construction
Build query text from available artist data:

{genre} artist from {primary_market}.
Monthly listeners: {monthly_listeners}.
Follower growth: {velocity_pct}% MoM.
Audio profile: {danceability} danceability, {energy} energy.
Press: {press_article_count} articles in 30 days.

## Interpreting similarity scores
| Score | Meaning |
|-------|---------|
| 0.90+ | Very strong match — high confidence |
| 0.75–0.89 | Good match — use with moderate confidence |
| 0.60–0.74 | Weak match — note in report |
| < 0.60 | No strong precedent |

## Outcome weighting
- Match to "success" artist + score > 0.80 → positive signal
- Match to "dropped" artist + score > 0.80 → risk flag
- Match to "developing" → neutral, precedent still in progress

## What to return
Top 3 matches with: artist_name, similarity_score, genre,
monthly_listeners_at_signing, label_tier, outcome

## Label tier decision logic
| Condition | Tier |
|-----------|------|
| < 500K listeners + strong DIY signals | TuneCore |
| > 500K listeners OR strong press | Premium Solutions |
| > 1M listeners | Premium Solutions (mandatory) |
| Priority genre + strategic market | Premium Solutions |