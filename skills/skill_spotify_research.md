# Skill: Spotify Research
**File**: `skills/skill_spotify_research.md`
**Used by**: `agents/triage_chain.py`, `agents/research_graph.py`

## Purpose
How to fetch, interpret, and score Spotify artist data for A&R
evaluation at Believe. This skill defines what data to collect,
how to interpret it, and what thresholds to use for PASS/WATCH/SIGN.

## API setup
- **Library**: spotipy
- **Auth**: Client Credentials flow (no user login needed)
- **Credentials**: SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in .env
- **Rate limit**: 30 requests/second

## What we fetch

### For triage (fast pass)
| Method | What it returns |
|--------|----------------|
| sp.search() | Find artist by name, get artist_id |
| sp.artist() | Followers, popularity score, genres |

### For deep research
| Method | What it returns |
|--------|----------------|
| sp.artist_top_tracks() | Top 5 tracks with popularity scores |
| sp.audio_features() | Danceability, energy, valence, tempo |
| sp.artist_related_artists() | Who Spotify groups them with |

## Scoring thresholds

| Metric | PASS | WATCH | SIGN |
|--------|------|-------|------|
| Monthly listeners | < 50K | 50K-500K | > 500K |
| MoM growth % | < 5% | 5-20% | > 20% |
| Active markets | 1-2 | 3-7 | 8+ |
| Popularity score | < 20 | 20-50 | > 50 |

## Points breakdown (out of 30 pts)
- >= 5M listeners → 30 pts
- >= 1M listeners → 22 pts
- >= 500K listeners → 16 pts
- >= 100K listeners → 10 pts
- >= 50K listeners → 5 pts
- < 50K listeners → 0 pts

## Audio features interpretation
| Feature | Low (< 0.4) | Mid (0.4-0.7) | High (> 0.7) |
|---------|------------|--------------|-------------|
| Danceability | Niche/artistic | Moderate appeal | Playlist ready |
| Energy | Calm/ambient | Balanced | Festival/live ready |
| Valence | Dark/atmospheric | Neutral | Upbeat/commercial |

## Monthly listeners note
Spotipy Client Credentials flow does not expose monthly listeners
directly. We use this proxy formula:
monthly_listeners_estimated = popularity_score x 80,000
Flag as velocity_estimated: true in output so the report
notes this is an approximation.

## Override rules
- If artist not found → raise ValueError, triage returns ERROR
- If multiple results → pick artist with highest follower count
- If popularity = 0 → very new artist, flag for manual check

## Error handling
| Error | Action |
|-------|--------|
| SpotifyException 404 | Artist not found — return error state |
| SpotifyException 429 | Rate limit — wait retry_after seconds, retry once |
| Connection timeout | Retry with 2s delay, max 3 attempts |
| Both APIs fail | Return ERROR decision, trigger Slack alert |

## Believe priority genres
If artist genre matches any of these → +10 pts to triage score.
If no match → +3 pts only.

hip-hop, electronic, latin, afrobeats, french-rap, indie-pop,
r-n-b, metal, bollywood, java-pop, punjabi, techno, house, alt-pop

## Believe label tier guidance
| Listeners | Tier |
|-----------|------|
| < 500K + strong DIY signals | TuneCore |
| > 500K | Premium Solutions |
| > 1M | Premium Solutions (mandatory) |

## Example output
{
  "artist_id": "abc123",
  "artist_name": "Nova Eclipse",
  "monthly_listeners": 1200000,
  "followers": 180000,
  "follower_velocity_pct": 0.0,
  "active_markets": 10,
  "genres": ["indie pop", "alt-pop"],
  "popularity": 72,
  "velocity_estimated": true
}