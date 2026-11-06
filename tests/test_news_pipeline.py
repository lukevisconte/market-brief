import unittest
from unittest.mock import patch

from news import (
    build_research_packet,
    fetch_configured_news,
    normalize_article,
    score_relevance,
)
from main import REQUIRED_SECTIONS, build_prompt, run, validate_brief


WATCHLIST = {"NVDA": "NVIDIA", "XOM": "Exxon Mobil"}


class NewsPipelineTests(unittest.TestCase):
    def test_normalization_adds_watchlist_entities_and_common_fields(self):
        article = normalize_article({
            "title": "NVIDIA raises data-center guidance",
            "summary": "The company cited demand.",
            "url": "https://example.com/nvda",
        }, "Reuters", WATCHLIST)
        self.assertEqual(article["source"], "Reuters")
        self.assertEqual(article["tickers"], ["NVDA"])
        self.assertIn("earnings", article["topics"])

    def test_deduplication_groups_similar_reporting_and_preserves_sources(self):
        articles = [
            {"source": "Reuters", "title": "Oil supply disruption lifts crude prices", "url": "a", "published_at": "2026-09-24T10:00:00+00:00", "summary": "", "topics": ["commodities"], "tickers": []},
            {"source": "CNBC", "title": "Crude prices rise after oil supply disruption", "url": "b", "published_at": "2026-09-24T11:00:00+00:00", "summary": "", "topics": ["commodities"], "tickers": []},
        ]
        packet = build_research_packet(articles)
        self.assertEqual(len(packet["events"]), 1)
        self.assertEqual(packet["events"][0]["sources"], ["CNBC", "Reuters"])

    def test_relevance_prioritizes_macro_and_watchlist_news(self):
        score = score_relevance({
            "title": "Federal Reserve signals rate cut",
            "summary": "Policy decision affects NVDA",
            "topics": ["monetary policy"],
            "tickers": ["NVDA"],
            "source": "Federal Reserve",
        })
        self.assertGreaterEqual(score, 55)

    @patch("news._fetch_feed", side_effect=RuntimeError("feed unavailable"))
    def test_source_failure_isolated(self, _fetch):
        with patch(
            "builtins.open",
            unittest.mock.mock_open(read_data=(
                "sources:\n  bad:\n    name: Bad Feed\n"
                "    enabled: true\n    feeds:\n"
                "      - https://example.com/rss\n"
            )),
        ):
            articles, failures = fetch_configured_news(WATCHLIST, "ignored")
        self.assertEqual(articles, [])
        self.assertEqual(failures, ["Bad Feed"])

    def test_empty_packet_keeps_failed_source_visible(self):
        packet = build_research_packet([], ["Reuters"])
        self.assertEqual(packet["events"], [])
        self.assertEqual(packet["unavailable_sources"], ["Reuters"])

    def test_prompt_supports_finnhub_only_run(self):
        prompt = build_prompt("premarket", [], {}, [], build_research_packet([]))
        self.assertIn("FINANCIAL NEWS EVENTS", prompt)
        self.assertIn("9. WHAT TO WATCH AT THE OPEN", prompt)

    def test_brief_validation_keeps_the_existing_mode_sections(self):
        headings = "\n".join([
            "1. WHAT MATTERS TODAY",
            "2. MARKET DASHBOARD",
            "3. GLOBAL MARKETS",
            "4. MACRO FACTORS",
            "5. LARGE-CAP STOCKS TO WATCH",
            "6. SMALLER / HIGH-BETA MOVERS",
            "7. MACRO → STOCK CONNECTIONS",
            "8. INVESTOR TAKEAWAY",
            "9. WHAT MATTERS FOR TOMORROW",
        ])
        self.assertTrue(validate_brief(headings, "close"))
        self.assertFalse(validate_brief(headings, "premarket"))

    @patch("main.time.sleep")
    @patch("main.requests.post")
    def test_claude_truncation_retries_with_a_shorter_instruction(self, post, _sleep):
        first = unittest.mock.Mock()
        first.json.return_value = {
            "content": [{"type": "text", "text": "Partial"}],
            "stop_reason": "max_tokens",
        }
        second = unittest.mock.Mock()
        second.json.return_value = {
            "content": [{"type": "text", "text": "Complete brief"}],
            "stop_reason": "end_turn",
        }
        post.side_effect = [first, second]

        from main import call_claude
        result = call_claude("Write a brief.", "test-key")

        self.assertEqual(result, "Complete brief")
        self.assertEqual(post.call_count, 2)
        retry_prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("concise and information-dense", retry_prompt)

    @patch("main.send_email")
    @patch("main.call_claude")
    @patch("main.fetch_configured_news")
    @patch("main.fetch_finnhub_news")
    @patch("main.fetch_quote")
    @patch("main.require_env", return_value="test")
    def test_run_supports_finnhub_only_and_external_news(
        self,
        _env,
        fetch_quote,
        fetch_finnhub,
        fetch_external,
        call_claude,
        send_email,
    ):
        fetch_quote.side_effect = lambda symbol, _key: {
            "symbol": symbol,
            "price": 100.0,
            "change_pct": 0.1,
        }
        fetch_finnhub.return_value = [{
            "source": "Finnhub",
            "title": "Federal Reserve signals rate cut",
            "url": "https://example.com/fed",
            "published_at": "2026-09-24T10:00:00+00:00",
            "summary": "Policy announcement.",
        }]
        complete_brief = "\n".join(
            REQUIRED_SECTIONS + ["9. WHAT MATTERS FOR TOMORROW"]
        )
        call_claude.return_value = complete_brief

        for external, expected in (
            ([], "Federal Reserve signals rate cut"),
            ([{
                "source": "Reuters",
                "title": "Oil supply disruption lifts crude prices",
                "url": "https://example.com/oil",
                "published_at": "2026-09-24T11:00:00+00:00",
                "summary": "Oil supplies are affected.",
                "tickers": [],
                "topics": ["commodities"],
            }], "Oil supply disruption lifts crude prices"),
        ):
            with self.subTest(external=bool(external)):
                fetch_external.return_value = (external, [])
                with patch("builtins.print"):
                    run("close")
                prompt = call_claude.call_args.args[0]
                self.assertIn(expected, prompt)
                self.assertTrue(send_email.called)
                send_email.reset_mock()
                call_claude.reset_mock()


if __name__ == "__main__":
    unittest.main()
