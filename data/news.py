import time
import requests
import urllib3
from config import settings
from utils.logger import setup_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = setup_logger("news")


# Keyword sentiment lexicon for crypto news headlines
_BULLISH_WORDS = {
    # Strong bullish
    "surge": 2, "surges": 2, "soar": 2, "soars": 2, "skyrocket": 2,
    "breakout": 2, "rally": 2, "rallies": 2, "moon": 2, "mooning": 2,
    "explosion": 2, "parabolic": 2, "all-time high": 2, "ath": 2,
    # Moderate bullish
    "bullish": 1.5, "pump": 1.5, "accumulation": 1.5, "accumulate": 1.5,
    "whales": 1, "whale": 1, "buying": 1, "bought": 1,
    "uptrend": 1.5, "breakup": 1.5, "recovery": 1.5, "recover": 1.5,
    "etf": 1.5, "approval": 1.5, "approved": 1.5, "partnership": 1,
    "adoption": 1, "institutional": 1, "inflow": 1, "inflows": 1,
    # Mild bullish
    "gain": 0.5, "gains": 0.5, "rise": 0.5, "rises": 0.5, "rising": 0.5,
    "climbs": 0.5, "up": 0.3, "higher": 0.5, "positive": 0.5,
    "support": 0.3, "upgrade": 0.5, "growth": 0.5, "growing": 0.5,
    "optimism": 0.5, "optimistic": 0.5, "confidence": 0.5,
}

_BEARISH_WORDS = {
    # Strong bearish
    "crash": -2, "crashes": -2, "plunge": -2, "plunges": -2, "collapse": -2,
    "dump": -2, "dumping": -2, "scam": -2, "hack": -2, "hacked": -2,
    "exploit": -2, "rug pull": -2, "rugpull": -2, "fraud": -2,
    "ban": -2, "banned": -2, "lawsuit": -2, "sec": -1.5,
    # Moderate bearish
    "bearish": -1.5, "sell-off": -1.5, "selloff": -1.5, "selling": -1,
    "downtrend": -1.5, "breakdown": -1.5, "fear": -1, "panic": -1,
    "outflow": -1, "outflows": -1, "liquidation": -1, "liquidated": -1,
    "warning": -1, "risk": -0.5, "regulation": -1, "crackdown": -1.5,
    # Mild bearish
    "drop": -0.5, "drops": -0.5, "fall": -0.5, "falls": -0.5, "falling": -0.5,
    "decline": -0.5, "declines": -0.5, "dip": -0.3, "low": -0.3,
    "lower": -0.5, "negative": -0.5, "weak": -0.5, "weakness": -0.5,
    "resistance": -0.3, "concern": -0.5, "uncertainty": -0.5,
    "pessimism": -0.5, "pessimistic": -0.5,
}


class NewsService:
    """CryptoPanic news sentiment with keyword-based analysis (free tier: no votes)."""

    BASE_URL = "https://cryptopanic.com/api/developer/v2/posts/"

    def __init__(self):
        self.api_key = settings.CRYPTOPANIC_API_KEY
        self.cache_ttl = settings.NEWS_CACHE_HOURS * 3600  # seconds
        self._cache: dict[str, dict] = {}  # coin -> {score, timestamp, headlines}
        self._last_request_time = 0.0
        self._last_error_time = 0.0
        self._error_backoff = 3600  # Wait 1 hour after errors before retrying

    def get_sentiment(self, symbols: list[str]) -> dict[str, dict]:
        """
        Get sentiment scores for symbols. Returns cached data if fresh.
        Makes at most 1 API call per coin that needs refresh.

        Returns: {"XRP/USDT": {"score": 0.6, "headlines": [...]}, ...}
        """
        now = time.time()
        result = {}
        needs_refresh = []

        # Check if any symbol needs a refresh
        for symbol in symbols:
            coin = symbol.split("/")[0]  # "XRP/USDT" -> "XRP"
            cached = self._cache.get(coin)
            if cached and (now - cached["timestamp"]) < self.cache_ttl:
                result[symbol] = {"score": cached["score"], "headlines": cached["headlines"]}
            else:
                needs_refresh.append(symbol)

        if needs_refresh and self.api_key:
            # Don't retry if we recently had an error
            if (now - self._last_error_time) < self._error_backoff:
                return result
            fresh_data = self._fetch_sentiment(needs_refresh)
            result.update(fresh_data)

        return result

    def _fetch_sentiment(self, symbols: list[str]) -> dict[str, dict]:
        """Single API call to get sentiment for all coins."""
        coins = list({s.split("/")[0] for s in symbols})
        coins_param = ",".join(coins)

        try:
            # Rate limit: max 2 req/sec
            elapsed = time.time() - self._last_request_time
            if elapsed < 0.5:
                time.sleep(0.5 - elapsed)

            data = self._api_call(coins_param)
            self._last_request_time = time.time()

            if data is None:
                self._last_error_time = time.time()
                return {}

            return self._parse_response(data, symbols, coins)

        except Exception as e:
            self._last_error_time = time.time()
            logger.warning(f"News API error, retry in {self._error_backoff // 60}min: {type(e).__name__}")
            return {}

    def _api_call(self, currencies: str) -> dict | None:
        """Fetch news from CryptoPanic API."""
        url = f"{self.BASE_URL}?auth_token={self.api_key}&currencies={currencies}&public=true&kind=news&regions=en"

        try:
            response = requests.get(url, timeout=10, verify=False)
            if response.status_code == 200:
                return response.json()
            logger.warning(f"CryptoPanic returned {response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"CryptoPanic request failed: {type(e).__name__}")
            return None

    def _score_text(self, text: str) -> float:
        """Score a headline/description using keyword sentiment analysis."""
        text_lower = text.lower()
        score = 0.0
        matches = 0

        for word, weight in _BULLISH_WORDS.items():
            if word in text_lower:
                score += weight
                matches += 1

        for word, weight in _BEARISH_WORDS.items():
            if word in text_lower:
                score += weight  # weight is already negative
                matches += 1

        if matches == 0:
            return 0.0

        # Normalize: scale to -1..+1 range
        # Typical headlines have 1-3 sentiment words, max ~4-5 weight
        return max(-1.0, min(1.0, score / 3.0))

    def _parse_response(self, data: dict, symbols: list[str], coins: list[str]) -> dict[str, dict]:
        """Parse API response and calculate per-coin sentiment scores using keyword analysis.

        Free tier only returns: title, description, published_at, created_at, kind.
        The currencies filter in the URL ensures we only get relevant articles,
        but we need to match articles to coins by checking title/description for coin names.
        """
        now = time.time()
        posts = data.get("results", [])

        if not posts:
            logger.info("No news articles returned from CryptoPanic")

        # If only one coin requested, all articles are for that coin
        # If multiple, we need to figure out which articles go with which coin
        coin_articles: dict[str, list[dict]] = {c: [] for c in coins}

        for post in posts:
            title = post.get("title", "")
            description = post.get("description", "") or ""

            if len(coins) == 1:
                coin_articles[coins[0]].append(post)
            else:
                # Match article to coins by checking if coin name appears in title
                text = f"{title} {description}".upper()
                matched = False
                for coin in coins:
                    if coin.upper() in text:
                        coin_articles[coin].append(post)
                        matched = True
                if not matched:
                    # If we can't match, assign to all coins (API already filtered)
                    for coin in coins:
                        coin_articles[coin].append(post)

        result = {}
        for symbol in symbols:
            coin = symbol.split("/")[0]
            articles = coin_articles.get(coin, [])

            if articles:
                # Score each article, weight recent articles more
                scores = []
                headlines = []
                for i, post in enumerate(articles[:10]):  # Max 10 articles
                    title = post.get("title", "")
                    desc = post.get("description", "") or ""
                    # Score from title (weighted more) and description
                    title_score = self._score_text(title)
                    desc_score = self._score_text(desc) * 0.5
                    article_score = title_score + desc_score
                    # Recency weight: first articles are more recent
                    recency = 1.0 - (i * 0.08)  # 1.0, 0.92, 0.84, ...
                    scores.append(article_score * recency)

                    if len(headlines) < 5:
                        headlines.append(title)

                # Average score across articles
                avg_score = sum(scores) / len(scores) if scores else 0.0
                score = max(-1.0, min(1.0, avg_score))
            else:
                score = 0.0
                headlines = []

            entry = {
                "score": round(score, 4),
                "headlines": headlines,
            }
            result[symbol] = entry

            # Update cache
            self._cache[coin] = {
                "score": entry["score"],
                "headlines": entry["headlines"],
                "timestamp": now,
            }

            logger.info(
                f"News sentiment {coin}: {entry['score']:+.2f} "
                f"({len(articles)} articles, keywords)"
            )

        return result

    def get_score(self, symbol: str) -> float:
        """Quick helper: get cached sentiment score for a single symbol. Returns 0 if no data."""
        coin = symbol.split("/")[0]
        cached = self._cache.get(coin)
        if cached:
            return cached["score"]
        return 0.0
