import pytest
from unittest.mock import patch, MagicMock

MOCK_SPOTIFY_SIGN = {
    "artist_id": "abc123",
    "artist_name": "Nova Eclipse",
    "monthly_listeners": 1200000,
    "followers": 180000,
    "follower_velocity_pct": 34.0,
    "active_markets": 14,
    "genres": ["indie pop", "alt-pop"],
    "popularity": 72,
    "velocity_estimated": True,
}

MOCK_SPOTIFY_PASS = {
    "artist_id": "xyz789",
    "artist_name": "Unknown Artist",
    "monthly_listeners": 2000,
    "followers": 300,
    "follower_velocity_pct": 1.0,
    "active_markets": 1,
    "genres": ["unknown"],
    "popularity": 5,
    "velocity_estimated": True,
}

MOCK_NEWS_SIGN = {
    "article_count": 18,
    "tier1_count": 3,
    "tier2_count": 7,
    "blog_count": 8,
    "top_headlines": ["NME: Nova Eclipse named one of 10 UK artists to watch"],
    "sources": ["NME", "DIY Magazine"],
    "recency_score": 0.85,
    "sentiment_score": 0.74,
    "press_score": 22,
}

MOCK_NEWS_PASS = {
    "article_count": 1,
    "tier1_count": 0,
    "tier2_count": 0,
    "blog_count": 1,
    "top_headlines": [],
    "sources": ["random-blog.com"],
    "recency_score": 0.1,
    "sentiment_score": 0.0,
    "press_score": 1,
}

MOCK_NEWS_WATCH = {
    "article_count": 4,
    "tier1_count": 0,
    "tier2_count": 1,
    "blog_count": 3,
    "top_headlines": ["Clash Music: Zara Beats releases new single"],
    "sources": ["Clash Music"],
    "recency_score": 0.5,
    "sentiment_score": 0.3,
    "press_score": 5,
}

MOCK_SPOTIFY_WATCH = {
    "artist_id": "watch001",
    "artist_name": "Zara Beats",
    "monthly_listeners": 340000,
    "followers": 55000,
    "follower_velocity_pct": 21.0,
    "active_markets": 8,
    "genres": ["hip-hop", "afrobeats"],
    "popularity": 45,
    "velocity_estimated": True,
}


class TestScoreArtist:

    def test_high_score_yields_sign(self):
        from agents.triage_chain import score_artist
        score, breakdown = score_artist(MOCK_SPOTIFY_SIGN, MOCK_NEWS_SIGN, "indie-pop")
        assert score >= 70, f"Expected SIGN score >= 70, got {score}"
        assert breakdown["listeners_pts"] > 0
        assert breakdown["press_pts"] > 0

    def test_low_score_yields_pass(self):
        from agents.triage_chain import score_artist
        score, breakdown = score_artist(MOCK_SPOTIFY_PASS, MOCK_NEWS_PASS, "unknown")
        assert score < 40, f"Expected PASS score <40, got {score}"

    def test_mid_score_yields_watch(self):
        from agents.triage_chain import score_artist
        score, breakdown = score_artist(MOCK_SPOTIFY_WATCH, MOCK_NEWS_WATCH, "hip-hop")
        assert 40 <= score < 70, f"Expected WATCH score 40-69, got {score}"

    def test_genre_fit_bonus(self):
        from agents.triage_chain import score_artist
        score_with_priority, _ = score_artist(MOCK_SPOTIFY_WATCH, MOCK_NEWS_WATCH, "electronic")
        score_without, _ = score_artist(MOCK_SPOTIFY_WATCH, MOCK_NEWS_WATCH, "unknown-genre")
        assert score_with_priority > score_without

    def test_score_capped_at_100(self):
        from agents.triage_chain import score_artist
        perfect_spotify = {**MOCK_SPOTIFY_SIGN, "monthly_listeners": 99000000,
                           "follower_velocity_pct": 999.0, "active_markets": 100}
        perfect_news = {**MOCK_NEWS_SIGN, "press_score": 100}
        score, _ = score_artist(perfect_spotify, perfect_news, "electronic")
        assert score <= 100


class TestClassifyDecision:

    def test_sign_threshold(self):
        from agents.triage_chain import classify_decision
        assert classify_decision(75, MOCK_SPOTIFY_SIGN, MOCK_NEWS_SIGN) == "SIGN"
        assert classify_decision(70, MOCK_SPOTIFY_SIGN, MOCK_NEWS_SIGN) == "SIGN"

    def test_watch_threshold(self):
        from agents.triage_chain import classify_decision
        assert classify_decision(55, MOCK_SPOTIFY_WATCH, MOCK_NEWS_WATCH) == "WATCH"
        assert classify_decision(40, MOCK_SPOTIFY_WATCH, MOCK_NEWS_WATCH) == "WATCH"

    def test_pass_threshold(self):
        from agents.triage_chain import classify_decision
        assert classify_decision(25, MOCK_SPOTIFY_PASS, MOCK_NEWS_PASS) == "PASS"
        assert classify_decision(0, MOCK_SPOTIFY_PASS, MOCK_NEWS_PASS) == "PASS"

    def test_automatic_pass_override(self):
        from agents.triage_chain import classify_decision
        tiny_spotify = {**MOCK_SPOTIFY_PASS, "monthly_listeners": 3000}
        tiny_news = {**MOCK_NEWS_PASS, "article_count": 1}
        assert classify_decision(60, tiny_spotify, tiny_news) == "PASS"

    def test_automatic_watch_minimum_for_large_artist(self):
        from agents.triage_chain import classify_decision
        big_spotify = {**MOCK_SPOTIFY_SIGN, "monthly_listeners": 2000000}
        result = classify_decision(30, big_spotify, MOCK_NEWS_PASS)
        assert result in ("WATCH", "SIGN")


class TestRunTriage:

    @patch("agents.triage_chain.get_artist_overview", return_value=MOCK_SPOTIFY_SIGN)
    @patch("agents.triage_chain.get_press_summary", return_value=MOCK_NEWS_SIGN)
    @patch("agents.triage_chain.get_press_score", return_value=22)
    @patch("agents.triage_chain._reasoning_chain")
    def test_full_triage_returns_sign(
        self, mock_chain, mock_press_score, mock_news, mock_spotify
    ):
        mock_chain.invoke.return_value = {"reasoning": "Strong metrics support SIGN."}
        from agents.triage_chain import run_triage
        result = run_triage("Nova Eclipse", "indie-pop")
        assert result["decision"] == "SIGN"
        assert result["score"] >= 70
        assert result["spotify_unavailable"] is False
        assert result["news_unavailable"] is False
        assert "reasoning" in result
        assert "signals" in result

    @patch("agents.triage_chain.get_artist_overview", side_effect=Exception("Spotify down"))
    @patch("agents.triage_chain.get_press_summary", side_effect=Exception("NewsAPI down"))
    def test_both_apis_fail_returns_error(self, mock_news, mock_spotify):
        from agents.triage_chain import run_triage
        result = run_triage("Unknown Artist", "pop")
        assert result["decision"] == "ERROR"
        assert result["spotify_unavailable"] is True
        assert result["news_unavailable"] is True

    @patch("agents.triage_chain.get_artist_overview", side_effect=Exception("Spotify down"))
    @patch("agents.triage_chain.get_press_summary", return_value=MOCK_NEWS_SIGN)
    @patch("agents.triage_chain.get_press_score", return_value=22)
    @patch("agents.triage_chain._reasoning_chain")
    def test_spotify_failure_continues_with_news(
        self, mock_chain, mock_press_score, mock_news, mock_spotify
    ):
        mock_chain.invoke.return_value = {"reasoning": "Based on press data only."}
        from agents.triage_chain import run_triage
        result = run_triage("Test Artist", "pop")
        assert result["decision"] != "ERROR"
        assert result["spotify_unavailable"] is True
        assert result["news_unavailable"] is False


class TestNewsTool:

    def test_tier1_outlet_scores_5(self):
        from tools.news_tool import _score_outlet
        assert _score_outlet("NME") == 5.0
        assert _score_outlet("Pitchfork") == 5.0
        assert _score_outlet("Resident Advisor") == 5.0

    def test_tier2_outlet_scores_2(self):
        from tools.news_tool import _score_outlet
        assert _score_outlet("Clash Music") == 2.0
        assert _score_outlet("Stereogum") == 2.0

    def test_unknown_outlet_scores_half(self):
        from tools.news_tool import _score_outlet
        assert _score_outlet("some-random-blog.com") == 0.5

    def test_press_score_capped_at_25(self):
        from tools.news_tool import get_press_score
        maxed_summary = {"tier1_count": 10, "tier2_count": 10, "blog_count": 10, "recency_score": 1.0}
        score = get_press_score(maxed_summary)
        assert score <= 25