# AGENTS.md
# A&R Artist Intelligence Agent — Technical Instructions

This file is read by AI coding assistants (Claude Code, Cursor, Copilot)
and human developers before modifying this codebase.

Read this before making any changes. It explains the architecture,
the two agents, every file's purpose, and the rules you must follow.

---

## Project overview

This project is an autonomous A&R research system for Believe, a global
digital music company. It evaluates artist candidates and generates
signing recommendation reports using two AI agents:

1. **Triage Agent** (LangChain) — fast 15-second PASS/WATCH/SIGN decision
2. **Research Agent** (LangGraph) — full 2-minute parallel research + report

The system is triggered via FastAPI endpoints, which are called by n8n
workflows or directly via curl.

---

## Repository structure

```
project3_autonomous_agent/
├── agents/
│   ├── __init__.py
│   ├── triage_chain.py        # Agent 1: LangChain triage chain
│   └── research_graph.py      # Agent 2: LangGraph research graph
├── api/
│   ├── __init__.py
│   └── main.py                # FastAPI app: /triage /research /health
├── data/
│   └── roster_seed.json       # 25 simulated Believe artist profiles
├── docs/
│   ├── agent_spec.md          # Spec written FOR the agent (business logic)
│   ├── api_setup.md           # API costs, limits, auth instructions
│   └── stories.md             # Agile backlog 14 user stories
├── reports/                   # Generated reports saved here (gitignored)
├── scripts/
│   └── ingest_roster.py       # One-time Pinecone ingestion script
├── skills/
│   ├── skill_spotify_research.md
│   ├── skill_news_analysis.md
│   ├── skill_roster_similarity.md
│   └── skill_report_synthesis.md
├── tests/
│   ├── __init__.py
│   └── test_triage_chain.py   # 17 unit tests, all mocked
├── tools/
│   ├── __init__.py
│   ├── base.py                # Retry decorator — used by ALL tools
│   ├── spotify_tool.py        # Spotify artist search + ID lookup
│   ├── lastfm_tool.py         # Last.fm listener counts + velocity proxy
│   ├── news_tool.py           # NewsAPI press coverage
│   ├── youtube_tool.py        # YouTube channel stats
│   └── pinecone_tool.py       # Pinecone vector similarity search
├── AGENTS.md                  # This file
├── README.md                  # Setup and usage instructions
├── .env                       # API keys — NEVER commit
├── .env.example               # Template with all required keys
├── .gitignore                 # Blocks .env, venv/, reports/
└── requirements.txt           # All Python dependencies, pinned versions
```

---

## Agent 1: Triage Chain

**File**: `agents/triage_chain.py`
**Framework**: LangChain LCEL
**Trigger**: `POST /triage` via `api/main.py`
**Runtime**: < 15 seconds

### What it does
Takes an artist name and genre, fetches streaming and press data,
scores the artist 0-100, and returns PASS / WATCH / SIGN with
a Claude-generated reasoning explanation.

### Input schema
```python
{
    "artist_name": str,   # as it appears on Spotify/Last.fm
    "genre": str,         # e.g. "electronic", "hip-hop"
    "market": str         # optional ISO code e.g. "US", "GB"
}
```

### Output schema
```python
{
    "artist_name": str,
    "score": int,                    # 0-100
    "decision": str,                 # "SIGN" | "WATCH" | "PASS" | "ERROR"
    "signals": {
        "monthly_listeners": int,    # weekly × 4 proxy from Last.fm
        "listeners": int,            # real weekly listeners from Last.fm
        "playcount": int,            # total career plays from Last.fm
        "follower_velocity_pct": float,  # estimated from playcount ratio
        "press_article_count": int,
        "press_tier1_count": int,
        "active_markets": int,
        "genres": list[str],
        "data_source": str,          # "spotify+lastfm" | "lastfm" | "spotify"
        "score_breakdown": dict,     # pts per dimension
    },
    "reasoning": str,                # Claude 2-3 sentence explanation
    "spotify_unavailable": bool,
    "news_unavailable": bool,
}
```

### Scoring weights
```
monthly_listeners : 30 pts  (scale: 0 at <50K, 30 at ≥5M)
follower_velocity : 25 pts  (scale: 0 at <5%, 25 at ≥50%)
press_score       : 25 pts  (tier-weighted, capped at 25)
market_diversity  : 10 pts  (active_markets // 2, capped at 10)
genre_fit         : 10 pts  (10 if Believe priority genre, else 3)
```

### Decision thresholds
```
score ≥ 70  → SIGN
score 40-69 → WATCH
score < 40  → PASS
```

### Override rules
```
listeners < 5,000 AND articles < 2  → force PASS
listeners ≥ 1,000,000 AND score < 40 → force WATCH minimum
```

### Data source logic
```
1. Call spotify_tool.get_artist_overview()
2. If data_limited: True → enrich with lastfm_tool.get_artist_overview()
3. If Spotify fails entirely → use lastfm_tool directly
4. If both fail → return ERROR decision
5. Always call news_tool.get_press_summary() independently
```

### LLM used
`claude-sonnet-4-5` via `langchain_anthropic.ChatAnthropic`
Temperature: 0.1 (low for consistent reasoning)

---

## Agent 2: Research Graph

**File**: `agents/research_graph.py`
**Framework**: LangGraph StateGraph
**Trigger**: `POST /research` via `api/main.py`
**Runtime**: up to 2 minutes

### What it does
Takes an artist name (pre-qualified by triage as SIGN), runs 4 research
nodes in parallel, then synthesises all data into a structured A&R
signing report using Claude.

### State schema
```python
class ResearchState(TypedDict):
    # Inputs
    artist_name: str
    genre: str
    market: str
    triage_score: int
    triage_signals: dict

    # Research results (populated by parallel nodes)
    spotify_data: dict      # from node_spotify_deep
    news_data: dict         # from node_news_analysis
    youtube_data: dict      # from node_youtube
    roster_matches: list    # from node_roster_rag

    # Error tracking
    errors: list            # accumulated across nodes

    # Output
    report_draft: str       # from node_synthesise
    final_report: str       # from node_format
    report_path: str        # saved file path
```

### Graph flow
```
START
  └─► node_validate_input
        └─► [PARALLEL — all 4 run simultaneously]
              ├─► node_spotify_deep    (Spotify + Last.fm)
              ├─► node_news_analysis   (NewsAPI)
              ├─► node_youtube         (YouTube Data API)
              └─► node_roster_rag      (Pinecone)
        └─► conditional routing:
              ├─► if errors ≥ 3 → node_error_report → END
              └─► if errors < 3 → node_synthesise → node_format → END
```

### Conditional routing
If 3 or more research nodes fail, the graph routes to `node_error_report`
which generates a partial report explaining what failed and escalates
to WATCH. This prevents silent failures.

### LLM used
`claude-sonnet-4-5` via `langchain_anthropic.ChatAnthropic`
Temperature: 0.2 (slightly higher for more natural report prose)

### Report output
Reports are saved to `reports/` directory as Markdown files.
Filename format: `YYYY-MM-DD_artist_name_SIGN.md`

---

## Tools

### tools/base.py
Contains `@retry_with_backoff(max_retries=3, base_delay=1.0)`.
**Every tool function must use this decorator.** No exceptions.
Implements exponential backoff: delays are 1s, 2s, 4s between retries.

### tools/spotify_tool.py
- `get_artist_overview(artist_name, market)` — artist search + ID
- `get_top_tracks(artist_id, market)` — top 5 tracks
- `get_audio_features(track_ids)` — danceability, energy, valence
- **Important**: Spotify dev mode (Feb 2026) restricts popularity/follower
  data. This tool detects the restriction and sets `data_limited: True`.
  The triage chain then enriches with Last.fm automatically.

### tools/lastfm_tool.py
- `get_artist_overview(artist_name)` — weekly listeners, playcount,
  genres, velocity proxy
- `get_top_tracks(artist_name)` — top tracks with play counts
- `get_similar_artists(artist_name)` — similar artist matches
- `get_artist_tags(artist_name)` — genre tags
- **Velocity proxy**: `_estimate_velocity(weekly_listeners, playcount)`
  uses `playcount / weekly_listeners` ratio to estimate MoM growth.
  Low ratio = new/viral (high velocity). High ratio = established (low velocity).
  Always sets `velocity_estimated: True`.

### tools/news_tool.py
- `get_press_summary(artist_name, days, genre)` — article count, outlet
  breakdown, sentiment, recency score
- `get_press_score(press_summary)` — converts to 0-25 score
- 24h in-process cache to preserve 100 req/day free quota
- Outlet tier classification: tier-1 (5pts), tier-2 (2pts), blog (0.5pts)

### tools/youtube_tool.py
- `get_channel_stats(artist_name)` — subscribers, views, upload cadence,
  last upload date
- Returns `{"available": False}` gracefully if channel not found

### tools/pinecone_tool.py
- `find_similar_artists(query_text, top_k)` — semantic search against
  25 artist profiles in `believe-roster` Pinecone index
- Embeds query using OpenAI `text-embedding-3-small` (1536 dims)
- Returns similarity scores + metadata (outcome, tier, listeners at signing)

---

## API

### api/main.py
FastAPI application with 3 endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Returns `{"status":"ok"}` — used by n8n |
| `/triage` | POST | Runs triage chain, returns decision |
| `/research` | POST | Runs research graph, returns report path |

Interactive docs: `http://127.0.0.1:8000/docs` (auto-generated by FastAPI)

### Running the API
```bash
uvicorn api.main:app --port 8000 --log-level warning
```

### n8n integration
n8n calls `/triage` via HTTP Request node, reads the `decision` field,
and routes: SIGN → `/research`, WATCH → Slack node, PASS → end.

---

## Skills directory

Skills files are the source of truth for agent reasoning logic.
**If you change how the agent makes decisions, update the relevant
skill file first, then the code.**

| Skill file | Used by | Covers |
|-----------|---------|--------|
| `skill_spotify_research.md` | triage_chain, research_graph | Spotify+Last.fm thresholds |
| `skill_news_analysis.md` | triage_chain, research_graph | Outlet tiers, scoring formula |
| `skill_roster_similarity.md` | research_graph | Pinecone query, score interpretation |
| `skill_report_synthesis.md` | research_graph | 9-section report template, Claude prompt |

---

## Coding rules — follow these always

### 1. Never hardcode API keys
All credentials must come from environment variables via `os.environ[]`
or `os.getenv()`. The `.env` file is loaded by `dotenv.load_dotenv()` at
the top of each agent and the API main file.

### 2. All tool calls must have retry logic
Use `@retry_with_backoff()` from `tools/base.py` on every function that
calls an external API. This is non-negotiable.

### 3. Graceful degradation over exceptions
Tools must return a structured error state, not raise unhandled exceptions.
If a tool fails after retries, return `{"available": False, "error": str(e)}`
and log the error. Let the agent continue with remaining sources.

### 4. Type hints required everywhere
All functions must have complete type annotations for parameters and
return values. This is enforced for readability and AI assistant support.

### 5. Flag proxies and estimates
Any value that is estimated or proxied (not a real measured value) must
be flagged in the return dict:
- `velocity_estimated: True` — velocity is a proxy
- `data_limited: True` — Spotify returned restricted data
- `listener_period: "weekly"` — Last.fm listeners are weekly, not monthly

### 6. Log all API calls
Use the module-level `logger = logging.getLogger(__name__)` for all logging.
Log: what you're fetching, what you got back (key numbers), any errors.

### 7. Never commit `.env`
The `.env` file contains real API keys. It is in `.gitignore`.
If you accidentally commit it, rotate all keys immediately.

### 8. Tests must not make real API calls
All tests in `tests/` use `unittest.mock.patch` to mock external calls.
Running `python -m pytest tests/ -v` must work without any API keys set.

### 9. Commit message format
```
feat(scope): description    # new feature
fix(scope): description     # bug fix
docs(scope): description    # documentation only
chore(scope): description   # maintenance, cleanup
```

### 10. Run tests before committing
```bash
python -m pytest tests/ -v
```
All 17 tests must pass before pushing to main.

---

## Environment variables required

```bash
ANTHROPIC_API_KEY       # Claude LLM
SPOTIFY_CLIENT_ID       # Spotify artist search
SPOTIFY_CLIENT_SECRET   # Spotify artist search
LASTFM_API_KEY          # Primary streaming metrics
NEWSAPI_KEY             # Press coverage
YOUTUBE_API_KEY         # Channel stats
PINECONE_API_KEY        # Roster vector search
PINECONE_INDEX          # "believe-roster"
OPENAI_API_KEY          # Embeddings for Pinecone ingestion
SLACK_BOT_TOKEN         # WATCH escalation messages
SLACK_CHANNEL_ID        # Target Slack channel
```

---

## Common tasks

### Add a new data source tool
1. Create `tools/new_tool.py`
2. Import and use `@retry_with_backoff` from `tools/base.py`
3. Add a skill file `skills/skill_new_tool.md`
4. Import in `agents/triage_chain.py` or `agents/research_graph.py`
5. Add unit tests with mocked responses in `tests/`
6. Add key to `.env.example` and `docs/api_setup.md`

### Change scoring thresholds
1. Update `skill_spotify_research.md` with new thresholds
2. Update `score_artist()` in `agents/triage_chain.py`
3. Update mock data in `tests/test_triage_chain.py` if needed
4. Run `python -m pytest tests/ -v` to verify

### Add a new report section
1. Update `skills/skill_report_synthesis.md` with new section template
2. Update the Claude prompt in `agents/research_graph.py node_synthesise`
3. Update `docs/agent_spec.md` section 9 list

### Re-ingest roster data
```bash
python scripts/ingest_roster.py
```
This is idempotent — upsert overwrites existing vectors.

### Run the full system locally
```bash
# Terminal 1
source venv/Scripts/activate          # Windows
uvicorn api.main:app --port 8000 --log-level warning

# Terminal 2
source venv/Scripts/activate
curl -X POST http://127.0.0.1:8000/triage \
  -H "Content-Type: application/json" \
  -d "{\"artist_name\": \"Rema\", \"genre\": \"afrobeats\"}"
```
