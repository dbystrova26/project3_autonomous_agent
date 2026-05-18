# API Setup Guide
**Project**: A&R Artist Intelligence Agent — Believe  
**Last updated**: May 2026

This document covers every API used in the project: how to get the key, what it costs, what the limits are, and how authentication works in the code.

---

## 1. Anthropic (Claude)

| | |
|---|---|
| **Used for** | LLM — triage reasoning + report synthesis |
| **Required** | Yes |
| **`.env` key** | `ANTHROPIC_API_KEY` |
| **Get it** | console.anthropic.com → Settings → API Keys |

### Cost
| Model | Input | Output |
|---|---|---|
| claude-3-5-sonnet | $3 / 1M tokens | $15 / 1M tokens |
| claude-3-haiku | $0.25 / 1M tokens | $1.25 / 1M tokens |

One full A&R report ≈ ~3,000 tokens total ≈ **< $0.05 per report**

### Free tier
New accounts get $5 free credit — enough for ~100 reports in development.

### Limits
- Rate limit: 50 requests/minute on free tier
- Max tokens per request: 200,000 (claude-3-5-sonnet)

### Authentication in code
```python
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
# reads ANTHROPIC_API_KEY automatically from environment
```

---

## 2. Spotify Web API

| | |
|---|---|
| **Used for** | Artist metrics — listeners, followers, markets, audio features |
| **Required** | Yes (Tool 1) |
| **`.env` keys** | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` |
| **Get it** | developer.spotify.com → Dashboard → Create App |

### Cost
- **Free** — no charges for API usage
- Requires **Spotify Premium account** (€10.99/month or €5.99/month student)
- 3-month free trial available at spotify.com/premium

### Setup steps
1. Go to developer.spotify.com/dashboard
2. Click **Create App**
3. Redirect URI: `http://127.0.0.1:8888/callback`
4. Select **Web API**
5. Go to Settings → copy **Client ID** and **Client Secret**

### Limits
- 30 requests/second
- No daily request cap for Client Credentials flow
- Some endpoints require user auth (we don't use those)

### Authentication in code
We use **Client Credentials flow** — no user login needed, just ID + Secret:
```python
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.environ["SPOTIFY_CLIENT_ID"],
    client_secret=os.environ["SPOTIFY_CLIENT_SECRET"]
))
```

### What we fetch
- `sp.search()` — find artist by name
- `sp.artist()` — followers, popularity, genres
- `sp.artist_top_tracks()` — top 5 tracks
- `sp.audio_features()` — danceability, energy, valence, tempo

---

## 3. NewsAPI

| | |
|---|---|
| **Used for** | Press coverage — article count, outlet tier, sentiment |
| **Required** | Yes (Tool 2) |
| **`.env` key** | `NEWSAPI_KEY` |
| **Get it** | newsapi.org/register — free, no card needed |

### Cost
- **Free tier: 100 requests/day** — enough for development
- Developer plan: $449/month (not needed for this project)

### Limits
| Tier | Requests/day | History | Sources |
|---|---|---|---|
| Free | 100 | 1 month | Limited |
| Developer | Unlimited | Full | All |

### Authentication in code
```python
from newsapi import NewsApiClient
client = NewsApiClient(api_key=os.environ["NEWSAPI_KEY"])
results = client.get_everything(q="artist name", language="en")
```

### What we fetch
- Article count for an artist in the last 30 days
- Source names (to score outlet tier)
- Headlines (for sentiment analysis)

---

## 4. YouTube Data API v3

| | |
|---|---|
| **Used for** | Channel stats — subscribers, views, upload cadence |
| **Required** | Yes (research agent) |
| **`.env` key** | `YOUTUBE_API_KEY` |
| **Get it** | console.cloud.google.com |

### Cost
- **Free** — 10,000 units/day at no charge
- No billing required unless you exceed the free quota

### Setup steps
1. Go to console.cloud.google.com
2. Create project: `ar-agent-dev`
3. APIs & Services → Library → search **YouTube Data API v3** → Enable
4. APIs & Services → Credentials → Create Credentials → API Key
5. Copy key into `.env`

### Limits
| Operation | Cost (units) | Daily free allowance |
|---|---|---|
| Channel search | 100 units | ~100 searches |
| Channel stats | 1 unit | ~10,000 lookups |
| Video stats | 1 unit | ~10,000 lookups |
| Playlist items | 1 unit | ~10,000 lookups |

For development (testing ~10 artists/day) you will never hit the limit.

### Authentication in code
```python
from googleapiclient.discovery import build
youtube = build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])
```

### What we fetch
- Channel subscriber count and total views
- Recent video view counts
- Upload frequency (days between uploads)
- Last upload date

---

## 5. Pinecone

| | |
|---|---|
| **Used for** | RAG — vector similarity search against Believe roster |
| **Required** | Yes |
| **`.env` keys** | `PINECONE_API_KEY`, `PINECONE_INDEX` |
| **Get it** | app.pinecone.io — free account |

### Cost
- **Free tier: 2GB storage, 1 index** — enough for this project
- Serverless plan: pay per use after free tier

### Index settings used
| Setting | Value |
|---|---|
| Index name | `believe-roster` |
| Dimensions | `1536` |
| Metric | `cosine` |
| Vector type | `Dense` |
| Cloud provider | AWS |
| Region | eu-west-1 (Ireland) |

### Setup steps
1. Go to app.pinecone.io → sign up
2. Create Index → name: `believe-roster`
3. Check **Custom settings**
4. Set dimensions: `1536`, metric: `cosine`, vector type: `Dense`
5. Cloud: AWS, Region: eu-west-1
6. Left sidebar → **API Keys** → Generate Key → copy

### Authentication in code
```python
from pinecone import Pinecone
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index(os.environ["PINECONE_INDEX"])
```

### How we use it
- Run `python scripts/ingest_roster.py` once to load 25 artist profiles
- At query time: embed candidate artist description → find top-5 similar roster artists
- Returns similarity score (0–1) + artist metadata (outcome, tier, listeners at signing)

---

## 6. OpenAI

| | |
|---|---|
| **Used for** | Embeddings only — converting artist profiles to vectors for Pinecone |
| **Required** | Yes (for `scripts/ingest_roster.py`) |
| **`.env` key** | `OPENAI_API_KEY` |
| **Get it** | platform.openai.com/api-keys |

### Cost
| Model | Price |
|---|---|
| text-embedding-3-small | $0.02 / 1M tokens |

Embedding 25 artist profiles ≈ **< $0.01 total** — essentially free.

### Limits
- Rate limit: 3,000 requests/minute on free tier
- More than enough for our 25-profile ingestion

### Authentication in code
```python
from openai import OpenAI
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
response = client.embeddings.create(
    model="text-embedding-3-small",
    input="artist description text"
)
vector = response.data[0].embedding  # 1536-dimensional list of floats
```

### Note
OpenAI is only called once during `ingest_roster.py`. After that, Pinecone stores the vectors and OpenAI is not called again during normal agent operation.

---

## 7. Slack

| | |
|---|---|
| **Used for** | WATCH escalation — sends alert to A&R manager with action buttons |
| **Required** | Yes (for human-in-the-loop) |
| **`.env` keys** | `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID` |
| **Get it** | api.slack.com/apps |

### Cost
- **Free** — Slack API is free for all workspaces

### Setup steps
1. Go to api.slack.com/apps → Create App → From Scratch
2. App name: `ar-agent-bot`, workspace: your Ironhack workspace
3. Left sidebar → **OAuth & Permissions**
4. Scroll to **Bot Token Scopes** → Add:
   - `chat:write` — allows bot to post messages
   - `channels:read` — allows bot to see channels
5. Scroll up → **Install to Workspace** → Allow
6. Copy **Bot User OAuth Token** (starts with `xoxb-`)
7. In Slack: create channel `ar-agent-alerts`
8. In the channel type: `/invite @ar-agent-bot`
9. Right-click channel → Copy Link → last part is the channel ID

### Authentication in code
```python
from slack_sdk import WebClient
client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
client.chat_postMessage(
    channel=os.environ["SLACK_CHANNEL_ID"],
    text="WATCH alert: artist needs review"
)
```

---

## Summary table

| API | Cost | Free limit | Card needed | Status |
|---|---|---|---|---|
| Anthropic | Pay per token | $5 free credit | No (trial) | ✓ configured |
| Spotify | Free (Premium req.) | Unlimited calls | Yes (Premium) | ✓ configured |
| NewsAPI | Free tier | 100 req/day | No | ✓ configured |
| YouTube | Free tier | 10,000 units/day | No | ✓ configured |
| Pinecone | Free tier | 2GB / 1 index | No | ✓ configured |
| OpenAI | Pay per token | ~free for embeddings | No (small usage) | ? pending |
| Slack | Free | Unlimited | No | ✓ configured |

---

## Running order

Once all keys are in `.env`, run in this order:

```bash
# 1. Activate venv
source venv/Scripts/activate        # Windows Git Bash
# source venv/bin/activate          # Mac/Linux

# 2. Install packages
pip install -r requirements.txt

# 3. Load roster data into Pinecone (one-time only)
python scripts/ingest_roster.py

# 4. Verify tests pass
python -m pytest tests/ -v

# 5. Start the API
uvicorn api.main:app --reload --port 8000
```
