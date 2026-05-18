# docs/stories.md
# Agile Sprint Backlog — A&R Artist Intelligence Agent
**Project**: Autonomous A&R Research & Signing Recommendation Agent
**Company**: Believe (music distribution & artist development)
**Duration**: 5 days (1 sprint = 1 day)
**Developer**: Daria Bystrova

---

## What is this document?

This is the Agile sprint backlog for the project. Before writing any code,
every feature was described as a **user story** — a small description of
what needs to be built from the perspective of the person who needs it.

Each story follows the format:
> As a [person], I want [something], so that [reason].

Each story includes:
- **Estimate**: how long it takes in hours
- **Dependencies**: what must be done first
- **Definition of done**: the exact criteria that prove it is finished

---

## Epics overview

| Epic | Stories | Sprint | Description |
|------|---------|--------|-------------|
| 1 — Infrastructure | US-01 to US-03 | Day 1 | Environment, APIs, database |
| 2 — Triage agent | US-04 to US-06 | Day 2 | LangChain fast decision chain |
| 3 — Research agent | US-07 to US-08 | Day 3 | LangGraph full research pipeline |
| 4 — Reliability | US-09 to US-11 | Day 4 | Error handling, human-in-loop |
| 5 — Documentation | US-12 to US-14 | Day 5 | Reports, skills, demo |

---

## Epic 1 — Infrastructure & integrations

### US-01 · Environment & repository setup
**Story**: As a developer, I want a fully configured project environment
so I can build without setup friction.

**Estimate**: 2h
**Dependencies**: none

**Tasks**:
- Create GitHub repository
- Set up Python virtual environment (`python -m venv venv`)
- Install core dependencies from `requirements.txt`
- Create `.env.example` with all required variable names
- Create `.gitignore` blocking `.env` and `venv/`
- Write initial `README.md`

**Definition of done**:
- `python -m pytest` runs without import errors
- `.env.example` lists all 10 required keys
- `venv/` is excluded from git
- README explains setup in under 10 steps

---

### US-02 · Streaming data tools — Spotify + Last.fm
**Story**: As the triage agent, I want to fetch artist streaming metrics
so I can score audience size and momentum.

**Estimate**: 3h
**Dependencies**: US-01

**Tasks**:
- Register Spotify app at developer.spotify.com
- Implement `tools/spotify_tool.py` with artist search and ID lookup
- Register Last.fm API key at last.fm/api
- Implement `tools/lastfm_tool.py` with:
  - `get_artist_overview()` returning weekly listeners, playcount, genres
  - `get_top_tracks()` returning top 5 tracks with play counts
  - `_estimate_velocity()` using playcount/listener ratio as MoM proxy
- Implement Spotify → Last.fm fallback logic when Spotify is dev-mode limited
- Add `@retry_with_backoff` decorator to all API calls

**Definition of done**:
- `get_artist_overview("Dua Lipa")` returns listeners > 0
- Velocity proxy returns a non-zero estimate
- Fallback triggers automatically when Spotify returns `data_limited: True`
- All functions have type hints and docstrings

---

### US-03 · NewsAPI press tool
**Story**: As the triage agent, I want to fetch press coverage data
so I can assess an artist's media traction and momentum.

**Estimate**: 2h
**Dependencies**: US-01

**Tasks**:
- Register NewsAPI key at newsapi.org
- Implement `tools/news_tool.py` with:
  - `get_press_summary()` returning article count, outlet breakdown, sentiment
  - `get_press_score()` returning 0-25 score
  - Tier-1/2/blog outlet classification
  - Recency weighting (last 7 days count double)
  - 24h in-process cache to preserve 100 req/day free quota
- Add retry logic and rate limit handling

**Definition of done**:
- Returns correct article count for a known artist
- `_score_outlet("NME")` returns 5.0
- `_score_outlet("unknown-blog.com")` returns 0.5
- Press score capped at 25

---

### US-04 · Pinecone vector database setup + roster ingestion
**Story**: As the research agent, I want to search Believe's artist roster
by similarity so I can benchmark candidates against proven signings.

**Estimate**: 3h
**Dependencies**: US-01

**Tasks**:
- Create Pinecone account and `believe-roster` index (dims=1536, cosine)
- Create `data/roster_seed.json` with 25 simulated Believe artist profiles
  covering: electronic, french-rap, afrobeats, latin, hip-hop, metal,
  bollywood, punjabi, indie-pop, r-n-b, j-pop
- Implement `scripts/ingest_roster.py` to embed profiles into Pinecone
- Implement `tools/pinecone_tool.py` with `find_similar_artists()`

**Definition of done**:
- `python scripts/ingest_roster.py` completes with "25 vectors ingested"
- `find_similar_artists("electronic artist Germany 2M listeners")` returns
  ≥ 3 results with similarity score > 0.5
- Pinecone index shows 25 vectors

---

## Epic 2 — Triage agent (LangChain)

### US-05 · LangChain triage chain — PASS/WATCH/SIGN decision
**Story**: As an A&R manager, I want the system to classify artists as
PASS/WATCH/SIGN in under 15 seconds so I can focus on promising candidates.

**Estimate**: 3h
**Dependencies**: US-02, US-03

**Tasks**:
- Implement `agents/triage_chain.py` with:
  - 5-dimension scoring (listeners 30pts, velocity 25pts, press 25pts,
    markets 10pts, genre fit 10pts)
  - `classify_decision()` with override rules
  - Spotify + Last.fm enrichment logic
  - Claude reasoning explanation via LangChain LCEL chain
- Test with 5 artists: 2 expected SIGN, 2 expected PASS, 1 WATCH

**Definition of done**:
- Correct decision for all 5 test artists
- Response time < 15s
- Output JSON validates against AGENTS.md schema
- `data_source` field shows "spotify+lastfm" when enrichment used

---

### US-06 · FastAPI endpoints
**Story**: As a user of the system, I want to trigger artist research by
sending a JSON POST so the system is easy to call from n8n or curl.

**Estimate**: 2h
**Dependencies**: US-05

**Tasks**:
- Implement `api/main.py` with:
  - `POST /triage` — runs triage chain
  - `POST /research` — runs full research graph
  - `GET /health` — health check
- Add Pydantic request/response models with validation
- Add structured logging

**Definition of done**:
- `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`
- `POST /triage` with valid artist returns decision in < 20s
- Invalid request (missing artist_name) returns 422 with clear error
- Interactive docs available at `http://127.0.0.1:8000/docs`

---

## Epic 3 — Full research agent (LangGraph)

### US-07 · LangGraph parallel research graph
**Story**: As the system, I want to run all research sources in parallel
so the full report completes in under 2 minutes.

**Estimate**: 4h
**Dependencies**: US-04, US-05

**Tasks**:
- Implement `agents/research_graph.py` with LangGraph `StateGraph`:
  - `ResearchState` TypedDict with all data fields
  - Nodes: validate → [spotify_deep, news_analysis, youtube, roster_rag]
    (parallel) → synthesise → format
  - Conditional routing: if errors ≥ 3 → error_report node
- Implement `tools/youtube_tool.py` with `get_channel_stats()`
- Integration test: all 4 nodes populate state without exceptions

**Definition of done**:
- Graph compiles without errors
- All 4 research nodes execute and populate their state keys
- Conditional error routing tested
- Parallel execution confirmed (log timestamps show overlap)

---

### US-08 · Claude report synthesis
**Story**: As an A&R manager, I want a structured readable report with
a clear recommendation so I can make a fast informed signing decision.

**Estimate**: 3h
**Dependencies**: US-07

**Tasks**:
- Implement `node_synthesise` using Claude claude-sonnet-4-5
- Build synthesis prompt from `skills/skill_report_synthesis.md`
- Implement `node_format` to produce Markdown with consistent sections
- Reports saved to `reports/` with date + artist + decision filename
- Generate 3 sample reports: pop (SIGN), afrobeats (WATCH), electronic (SIGN)

**Definition of done**:
- 3 sample reports committed to `reports/` directory
- Each report has all 9 required sections from skill file
- Report filename format: `YYYY-MM-DD_artist_SIGN.md`
- Reports readable by non-technical A&R manager

---

## Epic 4 — Reliability & human-in-the-loop

### US-09 · Slack WATCH escalation
**Story**: As an A&R manager, I want to receive a Slack message for
borderline artists so I can decide without doing manual research.

**Estimate**: 2h
**Dependencies**: US-06

**Tasks**:
- Configure Slack bot `ar-agent-bot` in workspace
- Create `#ar-agent-alerts` channel
- Implement Slack notification in n8n workflow for WATCH decisions
- Message includes: artist name, score, top 3 signals

**Definition of done**:
- WATCH artist generates Slack message in < 30s
- Message shows score and key signals clearly
- Bot is invited to the channel and can post

---

### US-10 · Retry and fallback logic for all API calls
**Story**: As a developer, I want the system to handle API failures
gracefully so reports are never silently wrong or missing.

**Estimate**: 2h
**Dependencies**: US-07

**Tasks**:
- Implement `tools/base.py` with `@retry_with_backoff(max_retries=3)`
- Apply decorator to all tool functions
- Test: mock Spotify to fail 2× → succeeds on 3rd call
- Test: Spotify fails entirely → Last.fm fallback activates
- Test: all sources fail → partial report with error notes generated
- Add `data_source` and `velocity_estimated` flags to all responses

**Definition of done**:
- All tools decorated with retry
- Spotify failure triggers Last.fm fallback automatically
- Full failure produces partial report with clear notes, not an exception
- Retry logs visible in uvicorn output

---

### US-11 · Unit test suite
**Story**: As a developer, I want automated tests so I can safely change
code without breaking the scoring logic.

**Estimate**: 2h
**Dependencies**: US-05

**Tasks**:
- Write `tests/test_triage_chain.py` with 17 tests covering:
  - Scoring: high/mid/low score thresholds
  - Genre fit bonus
  - Score capped at 100
  - SIGN/WATCH/PASS thresholds
  - Override rules (auto-PASS, auto-WATCH)
  - Full triage integration with mocked APIs
  - Spotify failure → continues with news data
  - Both APIs fail → ERROR decision
  - News outlet tier scoring

**Definition of done**:
- `python -m pytest tests/ -v` shows 17 passed
- Zero real API calls made during tests (all mocked)
- Tests run in < 30 seconds

---

## Epic 5 — Documentation & demo

### US-12 · Sample reports (minimum 3)
**Story**: As an evaluator, I want to see 3 sample reports covering
different genres and decisions to assess report quality and structure.

**Estimate**: 2h
**Dependencies**: US-08

**Reports to generate**:
- `report_nova_eclipse_pop.md` — SIGN, indie pop, UK artist
- `report_zara_beats_hiphop.md` — WATCH, hip-hop/afrobeats, Nigeria
- `report_circuit_edm.md` — SIGN, electronic, Germany

**Definition of done**:
- 3 files in `reports/` directory committed to GitHub
- Each report follows the 9-section template from skill file
- Reports use realistic but clearly fictional artist data
- Different genres and decisions represented

---

### US-13 · Skills directory + AGENTS.md
**Story**: As an evaluator, I want all agent skills and instructions
documented so the system is reproducible and auditable.

**Estimate**: 2h
**Dependencies**: all previous stories

**Files to create**:
- `AGENTS.md` — full agent instructions for triage and research agents
- `skills/skill_spotify_research.md` — Spotify + Last.fm data thresholds
- `skills/skill_news_analysis.md` — outlet tier classification and scoring
- `skills/skill_roster_similarity.md` — Pinecone query and interpretation
- `skills/skill_report_synthesis.md` — report template and Claude prompt
- `docs/agent_spec.md` — project specification written for the agent

**Definition of done**:
- All 6 files committed to GitHub
- Each skill file includes: purpose, inputs, outputs, decision logic, example
- AGENTS.md covers both triage chain and research graph

---

### US-14 · README + demo video
**Story**: As an evaluator, I want a complete README and 5-7 minute demo
so I can understand and replicate the system.

**Estimate**: 2h
**Dependencies**: all

**Tasks**:
- Write comprehensive README covering:
  - What the agent does (5 sentences max)
  - Architecture diagram
  - Data sources table (Spotify vs Last.fm vs NewsAPI vs YouTube)
  - Spotify limitations and how they are handled
  - Monthly listeners proxy explanation (weekly × 4)
  - Velocity proxy explanation (playcount/listener ratio)
  - Alternatives for real data in production
  - Setup instructions (Windows + Mac)
  - How to use (browser UI + curl + PowerShell)
  - Scoring logic table
- Record Loom: trigger → triage → SIGN → report → Slack

**Definition of done**:
- README renders correctly on GitHub
- Setup instructions work end-to-end from fresh clone
- Demo video is 5-7 minutes
- All 14 story definitions of done are checked off

---

## Sprint summary

| Sprint | Day | Stories | Focus |
|--------|-----|---------|-------|
| 1 | Day 1 | US-01 to US-04 | Setup, APIs, database |
| 2 | Day 2 | US-05 to US-06 | Triage agent + API |
| 3 | Day 3 | US-07 to US-08 | Research agent + reports |
| 4 | Day 4 | US-09 to US-11 | Reliability + tests |
| 5 | Day 5 | US-12 to US-14 | Docs + demo |

**Total estimated hours**: 34h across 5 days

---

## Velocity tracking

| Story | Estimated | Status |
|-------|-----------|--------|
| US-01 | 2h | ✓ Done |
| US-02 | 3h | ✓ Done |
| US-03 | 2h | ✓ Done |
| US-04 | 3h | ✓ Done |
| US-05 | 3h | ✓ Done |
| US-06 | 2h | ✓ Done |
| US-07 | 4h | ✓ Done |
| US-08 | 3h | ✓ Done |
| US-09 | 2h | In progress |
| US-10 | 2h | ✓ Done |
| US-11 | 2h | ✓ Done |
| US-12 | 2h | ✓ Done |
| US-13 | 2h | ✓ Done |
| US-14 | 2h | In progress |
