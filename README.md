# A&R Artist Intelligence Agent
**Autonomous artist research & signing recommendation system for independent digital music distribution**

Built by: Daria Bystrova | Ironhack AI Consulting Bootcamp | Project 3

---

## What this does

An A&R (Artists & Repertoire) manager at Believe receives hundreds of artist submissions globally. Manually researching each one takes hours. This agent automates the entire first-pass evaluation:

1. Submit an artist name via API
2. The agent pulls data from Spotify, Last.fm, YouTube, NewsAPI, and Believe's roster database
3. It scores the artist 0–100 and returns **PASS / WATCH / SIGN**
4. For SIGN decisions it generates a full structured report
5. For WATCH decisions it sends a Slack alert to the A&R manager

**No human effort needed until a decision actually requires human judgment.**

---

## Architecture

```
Your request (curl / n8n webhook)
        ↓
FastAPI /triage endpoint
        ↓
LangChain triage chain
  ├── Tool 1: Spotify API → artist search + ID
  │          ↓ if dev mode restricted
  │   Last.fm API → real listener counts (fallback/enrichment)
  └── Tool 2: NewsAPI → press coverage
        ↓
Score 0-100 → PASS / WATCH / SIGN
        ↓
    ┌─────────────────────────────────┐
    │                                 │
  PASS                             WATCH                          SIGN
  logged                       Slack alert               LangGraph research agent
                             to A&R manager                      ↓
                                                     ┌─────────────────────┐
                                                     │ Spotify+Last.fm     │
                                                     │ NewsAPI analysis    │ (parallel)
                                                     │ YouTube stats       │
                                                     │ Pinecone roster RAG │
                                                     └─────────────────────┘
                                                             ↓
                                                     Claude synthesises report
                                                             ↓
                                                     Report saved to reports/
                                                     + Slack summary sent
```

---

## Tech stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Agent framework | LangChain + LangGraph | LangChain for fast linear triage, LangGraph for parallel stateful research |
| LLM | Claude (Anthropic) | Report synthesis and triage reasoning |
| Vector database | Pinecone | Semantic similarity search against Believe's roster |
| Embeddings | OpenAI text-embedding-3-small | Artist profile vectorisation |
| API runtime | FastAPI + Uvicorn | HTTP endpoints for n8n and direct calls |
| Workflow automation | n8n | Webhook trigger, Slack output, Google Drive storage |
| Streaming data | Spotify + Last.fm | Two-source resilient data collection |
| Press data | NewsAPI | Press coverage and traction signals |
| Video data | YouTube Data API v3 | Channel stats and upload cadence |
| Testing | pytest + pytest-mock | 17 unit tests, no real API calls needed |

---

## Data sources — what we get from each

### Spotify
Spotify is the primary streaming data source. We use Client Credentials flow (no user login needed).

| Data point | Endpoint | Status |
|-----------|---------|--------|
| Artist search + ID | `/search` | ✓ Always available |
| Follower count | `/artists/{id}` | ✗ Restricted since Feb 2026 |
| Popularity score (0-100) | `/artists/{id}` | ✗ Restricted since Feb 2026 |
| Genre tags | `/artists/{id}` | ✗ Restricted since Feb 2026 |
| Top tracks | `/artists/{id}/top-tracks` | ✗ Restricted since Feb 2026 |
| Audio features | `/audio-features` | ✗ Restricted since Feb 2026 |
| Monthly listeners | Not in API | Never available (Spotify internal only) |

**Why Spotify is still included**: It provides the canonical artist ID (used to identify the exact artist across sources) and artist search. When Extended Quota is approved, all restricted endpoints become available automatically.

### Last.fm (fallback and enrichment)
Last.fm is free with no restrictions. When Spotify returns limited dev mode data, we automatically enrich with Last.fm.

| Data point | Endpoint | Status |
|-----------|---------|--------|
| Total unique listeners | `artist.getinfo` | ✓ Always available |
| Total play count | `artist.getinfo` | ✓ Always available |
| Genre tags | `artist.gettoptags` | ✓ Always available |
| Top tracks with play counts | `artist.gettoptracks` | ✓ Always available |
| Similar artists | `artist.getsimilar` | ✓ Always available |
| Weekly unique listeners | `artist.getinfo` | ✓ Always available — last 7 days |
| Monthly listeners (proxy) | Calculated: weekly × 4 | ✓ Estimated — see proxy section below |
| Follower velocity (MoM %) | Estimated via playcount proxy | ✓ Directional estimate — see velocity proxy section |

**Listener period note**: Last.fm exposes weekly unique listeners (last 7 days), not monthly. We convert weekly to a monthly proxy using weekly × 4. See the Monthly Listeners Proxy section below for full explanation.

**Velocity note**: Last.fm does not expose historical weekly snapshots, so real MoM growth cannot be measured directly. We use a playcount momentum proxy to estimate velocity. See the Velocity Proxy section below.


---

### Monthly listeners proxy — how we estimate it

Last.fm's API returns `stats.listeners` which is **weekly unique listeners** — the number of distinct users who played this artist in the last 7 days. This is a real measured number, not an estimate.

Spotify's industry-standard metric is **monthly listeners** (30-day rolling window). Our scoring thresholds are calibrated to monthly scale, so we convert:

```
monthly_listeners_proxy = weekly_listeners × 4
```

**Example — Dua Lipa:**
```
weekly_listeners  = 3,303,823   (real Last.fm data)
monthly_proxy     = 13,215,292  (weekly × 4)
```

**Is this accurate?**
The proxy is consistent — if Artist A has 2× the weekly listeners of Artist B, their monthly proxy will also be 2×. Relative scoring between artists is correct even if absolute numbers differ from Spotify.

For reference, Dua Lipa's real Spotify monthly listeners are ~80M. Our Last.fm proxy is 13.2M — lower because Last.fm's user base is smaller than Spotify's total. The proxy underestimates absolute reach but correctly ranks artists relative to each other.

**Why weekly × 4 specifically?**
For established artists, weekly listener counts are stable week-to-week. A 4× multiplier converts to monthly scale. This is a standard approximation used in music analytics when only weekly data is available.

**Alternatives to the proxy in a real deployment:**

| Option | How | Accuracy | Cost |
|--------|-----|---------|------|
| Spotify Extended Quota | Real monthly listeners direct from Spotify | Perfect | Free (approval required) |
| Chartmetric API | Aggregates Spotify + Apple + YouTube monthly listeners | Very high | ~$X/month |
| Soundcharts API | Similar to Chartmetric, music-industry focused | Very high | ~$X/month |
| Believe internal platform | Direct DSP data partnerships | Perfect | Internal only |
| Last.fm weekly × 4 | What we use now | Consistent proxy, underestimates absolute | Free |

**Key point for scoring**: Our thresholds were calibrated against the weekly × 4 proxy. A score of 78/100 for Dua Lipa correctly identifies her as a SIGN candidate even though the absolute listener number differs from Spotify. The ranking logic works correctly.


---

### Velocity proxy — how we estimate month-over-month growth

Last.fm's API only returns the **current week's** listener count — there are no historical snapshots available. You cannot ask "how many listeners did this artist have 4 weeks ago." This means real MoM growth cannot be directly calculated.

We estimate velocity using the **playcount-to-listeners ratio** as a momentum signal:

```
ratio = total_playcount / weekly_listeners
```

**The logic:**

A new or viral artist has many recent listeners but few total plays — they were just discovered, so plays haven't accumulated yet. This produces a **low ratio** and signals high growth.

An established artist has deep loyal fans who have played their music thousands of times — high total plays relative to listeners. This produces a **high ratio** and signals slower growth (steady, not breakout).

**Ratio → estimated velocity table:**

| Ratio | Artist type | Estimated MoM velocity |
|-------|------------|----------------------|
| < 5 | Brand new or going viral | 35% |
| 5–10 | New, growing fast | 25% |
| 10–20 | Strong growth phase | 18% |
| 20–50 | Developing, healthy growth | 12% |
| 50–100 | Established, moderate growth | 7% |
| 100–200 | Well established, slower growth | 4% |
| 200+ | Legacy / catalogue artist | 1.5% |

**Real examples from our tests:**

| Artist | Weekly listeners | Playcount | Ratio | Estimated velocity | Decision |
|--------|----------------|-----------|-------|-------------------|---------|
| Dua Lipa | 3,303,823 | 322,064,347 | 97.5 | 7% | SIGN (80/100) |
| Rema | 985,597 | 21,013,671 | 21.3 | 12% | WATCH (67/100) |

Rema's ratio of 21.3 correctly identifies him as a developing artist in a strong growth phase. Dua Lipa's ratio of 97.5 correctly identifies her as an established artist with steady but not explosive growth.

**Is this accurate?**
The proxy is directionally correct — it correctly ranks new artists as higher velocity than established ones. It is not a precise measurement. All velocity values are stored with `velocity_estimated: True` so reports are transparent about this.

**Alternatives for real velocity data:**

| Option | How | Accuracy |
|--------|-----|---------|
| Spotify Extended Quota | Real follower count snapshots over time | High |
| Chartmetric API | Weekly listener trend data from all DSPs | Very high |
| Soundcharts API | Similar to Chartmetric | Very high |
| Believe internal platform | Direct DSP partnerships, daily data | Perfect |
| Last.fm playcount proxy | What we use now | Directional only |

### How they work together

```
Agent calls Spotify search
    ↓
Spotify returns artist ID (always works)
    ↓
Agent calls Spotify for full artist data
    ↓
    ├── If Spotify returns full data (Extended Quota approved)
    │       Use Spotify for everything
    │
    └── If Spotify returns limited data (dev mode, Feb 2026 restrictions)
            Detect data_limited: true flag
            Call Last.fm for real listener counts
            Merge: Spotify ID + Last.fm metrics
            Result: spotify+lastfm combined source
```

### NewsAPI
| Data point | Available |
|-----------|---------|
| Article count (last 30 days) | ✓ |
| Outlet names (for tier scoring) | ✓ |
| Publication dates (for recency) | ✓ |
| Headline text (for sentiment) | ✓ |
| Full article body | ✗ Free tier only returns headlines |

### YouTube Data API v3
| Data point | Available |
|-----------|---------|
| Subscriber count | ✓ |
| Total view count | ✓ |
| Recent video views | ✓ |
| Upload frequency | ✓ |
| Last upload date | ✓ |

### Pinecone roster RAG
| Data point | Available |
|-----------|---------|
| Similar artist matches | ✓ |
| Signing outcome (success/dropped) | ✓ |
| Listeners at signing | ✓ |
| Label tier (TuneCore/Premium) | ✓ |

---

## Spotify restrictions — full explanation

### What changed (February 2026)
Spotify announced major API restrictions in February 2026 to protect artist data and control AI usage of their platform. All new developer apps created after this date are limited to:

- Only `/search` and basic metadata endpoints
- No follower counts, popularity scores, or genre data
- No top tracks or audio features
- No monthly listener data (this was never in the API anyway)

### Why this matters for A&R
With Spotify dev mode restrictions, our agent now uses two proxies: Last.fm weekly×4 for listeners and playcount momentum for velocity. Dua Lipa currently scores ~80/100 using both proxies. With real Spotify Extended Quota data, scores would be even more accurate but the directional decisions are already correct.

### How we handle it now
1. Spotify provides the artist ID (search always works)
2. We detect `data_limited: true` in the Spotify response
3. We automatically call Last.fm for real listener counts
4. We merge both sources into a combined `spotify+lastfm` result
5. All responses include `data_source` field showing which source was used

### How it would be eliminated in a real Believe deployment

**Option 1 — Spotify Extended Quota Mode**
Apply at developer.spotify.com → app Settings → Request Extended Quota Mode. Approval takes 1-2 weeks for legitimate business use cases. Once approved, all restricted endpoints return full data automatically. No code changes needed — just an approved app.

**Option 2 — Believe's internal data platform (most realistic)**
Believe processes 800 billion streams annually and has direct DSP partnerships with Spotify, Apple Music, YouTube Music, and others. In a real deployment, the agent would query Believe's internal analytics platform (likely Tableau, Snowflake, or a proprietary system) rather than the public Spotify API. This would provide:
- Real monthly listeners per market
- Week-over-week and month-over-month trends
- Platform breakdown (Spotify vs Apple vs YouTube)
- Playlist placement data
- Revenue per stream data

**Option 3 — Chartmetric or Soundcharts API**
Third-party music analytics platforms aggregate data from all DSPs including Spotify, bypassing API restrictions. Chartmetric ($X/month) provides real Spotify monthly listeners, TikTok stats, radio airplay, and playlist data. This is the fastest commercial solution.

---

## Known limitations summary

| Limitation | Impact | Workaround used | Real solution |
|-----------|--------|----------------|---------------|
| Spotify dev mode | No follower/popularity/velocity | Last.fm weekly×4 proxy | Extended Quota, Chartmetric, or Believe internal |
| No real MoM velocity | Proxy estimate only | Playcount/listener ratio proxy | Chartmetric API, Spotify Extended Quota, or Believe internal |
| NewsAPI free tier | 100 req/day, headlines only | 24h cache per artist | NewsAPI Developer plan |
| Pinecone mock data | 25 simulated profiles, not real | Realistic simulated data | Believe internal roster database |
| YouTube free tier | 10K units/day | Sufficient for development | YouTube Partner API |

---

## Setup — step by step

### Prerequisites
- Python 3.11 or higher
- Git
- VS Code (recommended)
- Accounts for: Anthropic, Spotify, Last.fm, NewsAPI, YouTube, Pinecone, OpenAI, Slack

### 1. Clone the repository
```bash
git clone https://github.com/dbystrova26/project3_autonomous_agent.git
cd project3_autonomous_agent
```

### 2. Create virtual environment
```bash
python -m venv venv
```

### 3. Activate virtual environment
**Windows (Git Bash):**
```bash
source venv/Scripts/activate
```
**Mac / Linux:**
```bash
source venv/bin/activate
```
You should see `(venv)` at the start of your terminal prompt.

### 4. Install dependencies
```bash
pip install -r requirements.txt
```

### 5. Set up API keys
```bash
cp .env.example .env
```
Open `.env` and fill in all values:

```
ANTHROPIC_API_KEY       → console.anthropic.com
SPOTIFY_CLIENT_ID       → developer.spotify.com/dashboard
SPOTIFY_CLIENT_SECRET   → developer.spotify.com/dashboard
LASTFM_API_KEY          → last.fm/api/account/create (free, instant)
NEWSAPI_KEY             → newsapi.org/register (free, instant)
YOUTUBE_API_KEY         → console.cloud.google.com
PINECONE_API_KEY        → app.pinecone.io
PINECONE_INDEX          → believe-roster
OPENAI_API_KEY          → platform.openai.com/api-keys
SLACK_BOT_TOKEN         → api.slack.com/apps
SLACK_CHANNEL_ID        → right-click channel in Slack → Copy Link → last part
```

See `docs/api_setup.md` for detailed instructions for each key.

### 6. Load artist data into Pinecone (one time only)
```bash
python scripts/ingest_roster.py
```
Embeds 25 artist profiles into Pinecone. Takes ~30 seconds. Run once only.

### 7. Run the tests
```bash
python -m pytest tests/ -v
```
Should show **17 passed**.

### 8. Start the API
```bash
uvicorn api.main:app --port 8000 --log-level warning
```
Keep this terminal open. Open a second terminal for commands.

### 9. Expose the API publicly with ngrok (required for n8n)

Your API runs on `localhost:8000` — only accessible from your own machine.
When you connect n8n Cloud (or any external service) to your agent, it needs
a public URL it can actually reach over the internet. This is what ngrok does.

**Why ngrok?**
ngrok creates a secure tunnel from a public URL (e.g. `https://abc123.ngrok-free.app`)
to your local port 8000. Requests that hit the public URL are forwarded to your
machine in real time. It is the standard developer tool for this — used universally
when testing webhooks, APIs, and integrations locally before deploying to a server.

Without ngrok, n8n Cloud sends a request to `localhost:8000` — which means
its own localhost, not yours. The request never reaches your machine.

**Setup (one time):**
1. Download ngrok from ngrok.com/download (Windows: just a .exe file)
2. Create a free account at ngrok.com
3. Authenticate: `ngrok config add-authtoken YOUR_TOKEN`

**Run ngrok (every session, in a separate terminal):**
```bash
ngrok http 8000
```

You will see:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000
```

Copy the `https://` URL — this is your public API address.
Use it everywhere n8n asks for your API endpoint.

**Test it works:**
```bash
curl https://abc123.ngrok-free.app/health
```
Expected: `{status:ok,service:ar-agent}`

**Important**: ngrok free tier gives you a random URL each session.
Every time you restart ngrok you get a new URL and must update it in n8n.
To get a fixed URL, upgrade to ngrok paid tier or deploy the API to a server.

**Running order (every dev session):**
```
Terminal 1: uvicorn api.main:app --port 8000 --log-level warning
Terminal 2: ngrok http 8000
Terminal 3: your commands (curl, pytest, etc.)
```

---

## How to use it

### Option A — Interactive browser UI (easiest)
Once the server is running, open in your browser:
```
http://127.0.0.1:8000/docs
```
FastAPI generates a full interactive UI. Click any endpoint, fill in the form, click Execute. No curl needed.

### Option B — Command line

**Health check:**
```bash
curl http://127.0.0.1:8000/health
```

**Run triage (Windows Git Bash):**
```bash
curl -X POST http://127.0.0.1:8000/triage -H "Content-Type: application/json" -d "{\"artist_name\": \"Dua Lipa\", \"genre\": \"pop\"}"
```

**Run triage (Mac/Linux):**
```bash
curl -X POST http://127.0.0.1:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"artist_name": "Dua Lipa", "genre": "pop"}'
```

**Run triage (PowerShell):**
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/triage" -Method POST -ContentType "application/json" -Body '{"artist_name": "Dua Lipa", "genre": "pop"}'
```

**Run full research report (triggers SIGN flow):**
```bash
curl -X POST http://127.0.0.1:8000/research -H "Content-Type: application/json" -d "{\"artist_name\": \"Fisher\", \"genre\": \"electronic\", \"triage_score\": 74}"
```
Report saved to `reports/` as a Markdown file.

### Example triage response
```json
{
  "artist_name": "Dua Lipa",
  "score": 0,
  "decision": "PASS",
  "signals": {
    "monthly_listeners": 3303823,
    "listeners": 3303823,
    "playcount": 322064347,
    "press_article_count": 44,
    "press_tier1_count": 6,
    "active_markets": 7,
    "genres": ["pop", "synthpop", "electropop"],
    "data_source": "spotify+lastfm"
  },
  "reasoning": "Dua Lipa is currently signed to Warner Music Group and is not available for Believe to sign. Believe only works with independent artists.",
  "spotify_unavailable": false,
  "news_unavailable": false
}
```

### Supported genres (Believe priority — +10 pts)
```
hip-hop, electronic, latin, afrobeats, french-rap, indie-pop,
r-n-b, metal, bollywood, java-pop, punjabi, techno, house, alt-pop, pop, rap
```

---

## Scoring logic

| Dimension | Weight | Source | Signal |
|-----------|--------|--------|--------|
| Monthly listeners | 30 pts | Last.fm (via Spotify+Last.fm) | Absolute audience size |
| Follower velocity | 25 pts | Playcount proxy (Last.fm) | Estimated MoM growth |
| Press coverage | 25 pts | NewsAPI | Tier-1/2 outlet count + recency |
| Market diversity | 10 pts | Derived from popularity | Number of active countries |
| Genre fit | 10 pts | Last.fm tags | Matches Believe priority genres |

| Score | Decision | Action |
|-------|----------|--------|
| 70–100 | SIGN | Full LangGraph research report generated |
| 40–69 | WATCH | Slack alert to A&R manager |
| 0–39 | PASS | Logged silently, no action |

### Major label check

Before scoring, the triage chain asks Claude whether the artist is currently
signed to a major label (Universal Music Group, Sony Music Entertainment,
or Warner Music Group) as their **primary** record label.

If yes → score is forced to 0 and decision is PASS immediately.
Believe only signs independent artists.

**Important distinction**: Distribution deals do not count.
Many independent artists distribute through major label networks
(e.g. Rema via Mavin/Universal distribution) — this does NOT make them
a major label artist. Only direct primary signings trigger PASS.

| Artist | Label status | Decision |
|--------|-------------|---------|
| Fisher | Independent (Sweat It Out) | SIGN (score 74) |
| Rema | Independent (Mavin Records) | WATCH (score 67) |
| Dua Lipa | Warner Music Group (primary) | PASS (score 0) |
| Gengahr | Independent (insufficient signals) | PASS (score 35) |

---

## Project structure

```
project3_autonomous_agent/
├── agents/
│   ├── triage_chain.py       # LangChain: Spotify+LastFM+News → PASS/WATCH/SIGN
│   └── research_graph.py     # LangGraph: parallel research + Claude report
├── api/
│   └── main.py               # FastAPI: /triage, /research, /health
├── data/
│   └── roster_seed.json      # 25 simulated Believe artist profiles
├── docs/
│   ├── agent_spec.md         # Project spec written for the agent
│   ├── api_setup.md          # API costs, limits, auth instructions
│   └── stories.md            # Agile backlog (14 user stories)
├── reports/                  # Generated A&R reports saved here
├── scripts/
│   └── ingest_roster.py      # Loads roster data into Pinecone (run once)
├── skills/
│   ├── skill_spotify_research.md
│   ├── skill_news_analysis.md
│   ├── skill_roster_similarity.md
│   └── skill_report_synthesis.md
├── tests/
│   └── test_triage_chain.py  # 17 unit tests
├── tools/
│   ├── base.py               # Retry decorator for all API calls
│   ├── spotify_tool.py       # Spotify API wrapper (artist ID + search)
│   ├── lastfm_tool.py        # Last.fm API wrapper (listener counts + tracks)
│   ├── news_tool.py          # NewsAPI wrapper
│   ├── youtube_tool.py       # YouTube Data API wrapper
│   └── pinecone_tool.py      # Pinecone vector search
├── AGENTS.md                 # Agent instructions for both agents
├── .env.example              # Environment variable template
├── .gitignore                # Prevents secrets from being committed
└── requirements.txt          # All Python dependencies
```

---

## Sample reports

The  directory contains 4 real agent-generated reports
demonstrating all decision types:

| File | Artist | Genre | Decision | Reason |
|------|--------|-------|---------|--------|
|  +  | Fisher | Electronic | SIGN (74/100) | Independent artist, strong streaming + press |
|  +  | Rema | Afrobeats | WATCH (67/100) | Borderline — good signals but below SIGN threshold |
|  +  | Dua Lipa | Pop | PASS (0/100) | Signed to Warner Music Group — unavailable |
|  +  | Gengahr | Indie | PASS (35/100) | Insufficient streaming and press signals |

Each report is saved as both Markdown and PDF automatically.
Reports include 9 sections: executive summary, artist overview,
streaming analysis, press analysis, digital presence, roster comparison,
risk factors, recommendation, and data sources.

---

## Future improvements

- Web interface for non-technical A&R managers (planned for next sprint)
- Real Spotify data once Extended Quota Mode approved
- Chartmetric API integration for MoM velocity data
- Real Believe roster data via internal API
- n8n webhook for fully automated pipeline (no curl needed)
- Multi-artist comparison reports
- Weekly automated monitoring for WATCH artists

---

## Agile planning

Full sprint plan: `docs/stories.md` — 14 user stories across 5 sprints.
