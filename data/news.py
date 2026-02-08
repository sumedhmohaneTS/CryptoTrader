import time
import requests
from config import settings
from utils.logger import setup_logger

logger = setup_logger("news")


class NewsService:
    """CryptoPanic news sentiment with aggressive caching (100 req/month limit)."""

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
        Makes at most 1 API call for all symbols combined.

        Returns: {"XRP/USDT": {"score": 0.6, "headlines": [...]}, ...}
        """
        now = time.time()
        result = {}
        needs_refresh = False

        # Check if any symbol needs a refresh
        for symbol in symbols:
            coin = symbol.split("/")[0]  # "XRP/USDT" -> "XRP"
            cached = self._cache.get(coin)
            if cached and (now - cached["timestamp"]) < self.cache_ttl:
                result[symbol] = {"score": cached["score"], "headlines": cached["headlines"]}
            else:
                needs_refresh = True

        if needs_refresh and self.api_key:
            # Don't retry if we recently had an error
            if (now - self._last_error_time) < self._error_backoff:
                return result
            fresh_data = self._fetch_sentiment(symbols)
            result.update(fresh_data)

        return result

    def _fetch_sentiment(self, symbols: list[str]) -> dict[str, dict]:
        """Single API call to get sentiment for all coins."""
        coins = [s.split("/")[0] for s in symbols]
        coins_param = ",".join(set(coins))

        try:
            # Rate limit: max 2 req/sec
            elapsed = time.time() - self._last_request_time
            if elapsed < 0.5:
                time.sleep(0.5 - elapsed)

            response = requests.get(
                self.BASE_URL,
                params={
                    "auth_token": self.api_key,
                    "currencies": coins_param,
                    "public": "true",
                    "kind": "news",
                    "regions": "en",
                },
                timeout=15,
            )
            self._last_request_time = time.time()

            if response.status_code != 200:
                self._last_error_time = time.time()
                logger.warning(f"CryptoPanic API returned {response.status_code}, will retry in {self._error_backoff // 60}min")
                return {}

            data = response.json()
            return self._parse_response(data, symbols)

        except Exception as e:
            self._last_error_time = time.time()
            logger.warning(f"News API unavailable, will retry in {self._error_backoff // 60}min: {type(e).__name__}")
            return {}

    def _parse_response(self, data: dict, symbols: list[str]) -> dict[str, dict]:
        """Parse API response and calculate per-coin sentiment scores."""
        now = time.time()
        coin_votes: dict[str, dict] = {}  # coin -> {pos, neg, headlines}

        for post in data.get("results", []):
            votes = post.get("votes", {})
            pos = votes.get("positive", 0)
            neg = votes.get("negative", 0)
            important = votes.get("important", 0)
            title = post.get("title", "")

            # v2 API uses "instruments" instead of "currencies"
            instruments = post.get("instruments", []) or post.get("currencies", [])
            for instrument in instruments:
                code = instrument.get("code", "")
                if code not in coin_votes:
                    coin_votes[code] = {"pos": 0, "neg": 0, "important": 0, "headlines": []}
                coin_votes[code]["pos"] += pos
                coin_votes[code]["neg"] += neg
                coin_votes[code]["important"] += important
                if len(coin_votes[code]["headlines"]) < 5:
                    coin_votes[code]["headlines"].append(title)

        result = {}
        for symbol in symbols:
            coin = symbol.split("/")[0]
            cv = coin_votes.get(coin)
            if cv:
                total = cv["pos"] + cv["neg"]
                score = (cv["pos"] - cv["neg"]) / total if total > 0 else 0.0
                # Weight by importance
                if cv["important"] > 3:
                    score *= 1.2  # Amplify if many important votes
                score = max(-1.0, min(1.0, score))
            else:
                score = 0.0

            entry = {
                "score": round(score, 4),
                "headlines": cv["headlines"] if cv else [],
            }
            result[symbol] = entry

            # Update cache
            self._cache[coin] = {
                "score": entry["score"],
                "headlines": entry["headlines"],
                "timestamp": now,
            }

            logger.info(f"News sentiment {coin}: {entry['score']:+.2f} ({cv['pos'] if cv else 0}+/{cv['neg'] if cv else 0}-)")

        return result

    def get_score(self, symbol: str) -> float:
        """Quick helper: get cached sentiment score for a single symbol. Returns 0 if no data."""
        coin = symbol.split("/")[0]
        cached = self._cache.get(coin)
        if cached:
            return cached["score"]
        return 0.0
