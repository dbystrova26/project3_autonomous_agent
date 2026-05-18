# A&R Artist Intelligence Agent
**Autonomous artist research & signing recommendation system for Believe**

Built by: Daria Bystrova | Ironhack Data Analytics Bootcamp | Project 3

---

## What this does

An A&R (Artists & Repertoire) manager at Believe receives hundreds of artist submissions globally. Manually researching each one takes hours. This agent automates the entire first-pass evaluation:

1. Submit an artist name via API
2. The agent pulls data from Spotify, YouTube, NewsAPI, and Believe's roster database
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
  ├── Tool 1: Spotify API → streaming metrics
  └── Tool 2: NewsAPI → press coverage
        ↓
Score 0-100 → PASS / WATCH / SIGN
        ↓
    ┌───────────────────────────────┐
    │                               │
  PASS                           WATCH                          SIGN
  logged                     Slack alert               LangGraph research agent
                           to A&R manager                      ↓
                                                   ┌─────────────────────┐
                                                   │ Spotify deep dive   │
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
| APIs | Spotify, NewsAPI, YouTube | Real data sources |
| Testing | pytest + pytest-mock | 17 unit tests, no real API calls needed |

---

## Known limitations & data mocking

### Spotify dev mode restriction
Spotify has restricted their API since April 2025. New apps in **Development Mode** only return `name`, `type`, `uri`, and `images` — no `followers`, `popularity`, `genres`, or `audio_features`.

**What we did**: The agent detects this limitation and falls back to mock estimates:
- Monthly listeners: 500,000 (mid-range estimate)
- Followers: 100,000
- Follower velocity: 15% MoM
- Active markets: 8
- All flagged with `data_limited: true` in the response

**How to fix this**: Request Extended Quota Mode from Spotify:
1. Go to developer.spotify.com/dashboard
2. Click your app → Settings
3. Scroll to **Request Extended Quota Mode**
4. Fill in the form explaining your use case
5. Wait 1-2 business days for approval

Once approved, real Spotify data will flow automatically — no code changes needed.

### NewsAPI free tier
Free tier limits to 100 requests/day and 30 days of article history. Results are cached per artist for 24 hours to preserve quota. For production, upgrade to the Developer plan.

### Pinecone roster data
The `believe-roster` Pinecone index contains **25 simulated artist profiles** — not real Believe artist data. In a real deployment this would be populated with actual signed artist data from Believe's systems.

### YouTube API
YouTube Data API v3 free tier allows 10,000 units/day. Each artist lookup costs ~103 units. This supports ~97 artist lookups per day for free.

---

## Setup — step by step

### Prerequisites
- Python 3.11 or higher
- Git
- A terminal (VS Code terminal recommended)
- Accounts for: Anthropic, Spotify, NewsAPI, YouTube, Pinecone, OpenAI, Slack

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
Open `.env` in any text editor and fill in all values. See `docs/api_setup.md` for where to get each key.

**Required keys:**
```
ANTHROPIC_API_KEY       → console.anthropic.com
SPOTIFY_CLIENT_ID       → developer.spotify.com/dashboard
SPOTIFY_CLIENT_SECRET   → developer.spotify.com/dashboard
NEWSAPI_KEY             → newsapi.org/register
YOUTUBE_API_KEY         → console.cloud.google.com
PINECONE_API_KEY        → app.pinecone.io
PINECONE_INDEX          → believe-roster (type this exactly)
OPENAI_API_KEY          → platform.openai.com/api-keys
SLACK_BOT_TOKEN         → api.slack.com/apps
SLACK_CHANNEL_ID        → right-click channel in Slack → Copy Link → last part
```

### 6. Load artist data into Pinecone (one time only)
```bash
python scripts/ingest_roster.py
```
This embeds 25 artist profiles into your Pinecone index. Takes about 30 seconds. Only needs to be run once.

### 7. Run the tests
```bash
python -m pytest tests/ -v
```
Should show **17 passed**. If anything fails, check your file structure matches the project layout below.

### 8. Start the API
```bash
uvicorn api.main:app --port 8000 --log-level warning
```
Keep this terminal open — the API runs here. You need a second terminal for commands.

---

## How to use it

### Test the API is running
Open a second terminal, activate venv, then:
```bash
curl http://127.0.0.1:8000/health
```
Expected response: `{"status":"ok","service":"ar-agent"}`

### Run a triage on an artist

**Windows Git Bash:**
```bash
curl -X POST http://127.0.0.1:8000/triage -H "Content-Type: application/json" -d "{\"artist_name\": \"Dua Lipa\", \"genre\": \"pop\"}"
```

**Mac / Linux:**
```bash
curl -X POST http://127.0.0.1:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"artist_name": "Dua Lipa", "genre": "pop"}'
```

**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/triage" -Method POST -ContentType "application/json" -Body '{"artist_name": "Dua Lipa", "genre": "pop"}'
```

### Example response
```json
{
  "artist_name": "Dua Lipa",
  "score": 56,
  "decision": "WATCH",
  "signals": {
    "monthly_listeners": 500000,
    "press_article_count": 44,
    "press_tier1_count": 6,
    "active_markets": 8
  },
  "reasoning": "Dua Lipa shows strong press traction with 44 articles and 6 tier-1 outlets including Billboard and Rolling Stone. Streaming estimates are mid-range pending Spotify Extended Access approval. Recommend WATCH pending real streaming data confirmation.",
  "spotify_unavailable": false,
  "news_unavailable": false
}
```

### Run a full research report
Only works when decision = SIGN. Change artist to trigger SIGN (score >= 70):
```bash
curl -X POST http://127.0.0.1:8000/research -H "Content-Type: application/json" -d "{\"artist_name\": \"Artist Name\", \"genre\": \"electronic\", \"triage_score\": 85}"
```
Report is saved to `reports/` folder as a Markdown file.

### Supported genres (Believe priority genres)
```
hip-hop, electronic, latin, afrobeats, french-rap, indie-pop,
r-n-b, metal, bollywood, java-pop, punjabi, techno, house, alt-pop
```
Using a priority genre adds +10 pts to the triage score.

---

## Project structure

```
project3_autonomous_agent/
├── agents/
│   ├── triage_chain.py       # LangChain: Spotify + News → PASS/WATCH/SIGN
│   └── research_graph.py     # LangGraph: parallel research + Claude report
├── api/
│   └── main.py               # FastAPI endpoints: /triage, /research, /health
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
│   ├── spotify_tool.py       # Spotify API wrapper
│   ├── news_tool.py          # NewsAPI wrapper
│   ├── youtube_tool.py       # YouTube Data API wrapper
│   └── pinecone_tool.py      # Pinecone vector search
├── AGENTS.md                 # Agent instructions for both agents
├── .env.example              # Environment variable template
├── .gitignore                # Prevents secrets from being committed
└── requirements.txt          # All Python dependencies
```

---

## Scoring logic

| Dimension | Weight | Signal |
|-----------|--------|--------|
| Monthly listeners | 30 pts | Absolute audience size |
| Follower velocity | 25 pts | Month-over-month growth |
| Press coverage | 25 pts | Tier-1/2 outlet count + recency |
| Market diversity | 10 pts | Number of active countries |
| Genre fit | 10 pts | Matches Believe priority genres |

| Score | Decision | Action |
|-------|----------|--------|
| 70–100 | SIGN | Full research report generated |
| 40–69 | WATCH | Slack alert to A&R manager |
| 0–39 | PASS | Logged silently |

---

## Future improvements

- Web interface for non-technical A&R managers (planned)
- Real Spotify data once Extended Quota approved
- Real Believe roster data via internal API integration
- n8n webhook for fully automated trigger (no curl needed)
- Multi-artist comparison reports
- Weekly monitoring for WATCH artists

---

## API documentation

Once the server is running, visit:
```
http://127.0.0.1:8000/docs
```
FastAPI generates interactive documentation automatically — you can test all endpoints directly in the browser without curl.

---

## Running tests without API keys

All tests use mocked API responses. You can run the test suite without any real API keys:
```bash
python -m pytest tests/ -v
```

---

## Agile planning

Full sprint plan with user stories, estimates, dependencies, and definitions of done:
- See `docs/stories.md`
- 14 user stories across 5 sprints (1 sprint = 1 day)
