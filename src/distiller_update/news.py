import json
import urllib.parse
import urllib.request
from datetime import datetime

import structlog

from .models import Config, NewsResult

logger = structlog.get_logger()

# Maximum news content size (4KB)
MAX_NEWS_SIZE = 4096

# Allowed URL schemes for security
ALLOWED_SCHEMES = {"http", "https"}

# Acceptable content types for news
ALLOWED_CONTENT_TYPES = {"text/plain", "text/html", "text/markdown", "application/octet-stream"}


class NewsFetcher:
    """Fetches and caches news from configured URL."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.cache_file = config.cache_dir / "news.json"

    def fetch(self) -> NewsResult | None:
        """Fetch news from URL with timeout and size validation."""
        if not self.config.news_enabled:
            logger.debug("News fetching disabled")
            return None

        # Validate URL scheme
        parsed_url = urllib.parse.urlparse(self.config.news_url)
        if parsed_url.scheme.lower() not in ALLOWED_SCHEMES:
            logger.error(
                "Invalid URL scheme for news fetch",
                url=self.config.news_url,
                scheme=parsed_url.scheme,
                allowed=list(ALLOWED_SCHEMES),
            )
            return self.get_cached()

        try:
            logger.info("Fetching news", url=self.config.news_url)

            req = urllib.request.Request(
                self.config.news_url,
                headers={"User-Agent": "distiller-update/2.1.0"},
            )

            with urllib.request.urlopen(req, timeout=self.config.news_fetch_timeout) as response:
                content_type = (
                    response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                )
                if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                    logger.warning(
                        "Unexpected content type for news",
                        content_type=content_type,
                        allowed=list(ALLOWED_CONTENT_TYPES),
                    )

                # Read with size limit
                content = response.read(MAX_NEWS_SIZE + 1).decode("utf-8")

                if len(content) > MAX_NEWS_SIZE:
                    logger.warning(
                        "News content exceeds size limit",
                        size=len(content),
                        limit=MAX_NEWS_SIZE,
                    )
                    content = content[:MAX_NEWS_SIZE]

                result = NewsResult(
                    content=content.strip(),
                    fetched_at=datetime.now(),
                    cache_ttl=self.config.news_cache_ttl,
                )

                self._save_cache(result)
                logger.info("News fetched successfully", size=len(content))
                return result

        except urllib.error.HTTPError as e:
            logger.warning("HTTP error fetching news", status=e.code, reason=e.reason)
            return self.get_cached()
        except urllib.error.URLError as e:
            logger.warning("Network error fetching news", error=str(e.reason))
            return self.get_cached()
        except TimeoutError:
            logger.warning("Timeout fetching news")
            return self.get_cached()
        except Exception as e:
            logger.error("Unexpected error fetching news", error=str(e))
            return self.get_cached()

    def get_cached(self) -> NewsResult | None:
        """Load cached news from disk."""
        if not self.cache_file.exists():
            logger.debug("No cached news available")
            return None

        try:
            with open(self.cache_file) as f:
                data = json.load(f)
                result = NewsResult.model_validate(data)

                if result.is_expired:
                    logger.debug(
                        "Cached news is expired",
                        age=(datetime.now() - result.fetched_at).total_seconds(),
                    )
                    return None

                logger.debug(
                    "Using cached news",
                    age=(datetime.now() - result.fetched_at).total_seconds(),
                )
                return result

        except Exception as e:
            logger.debug("Failed to load cached news", error=str(e))
            return None

    def _save_cache(self, result: NewsResult) -> None:
        """Save news result to cache file."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = result.model_dump(mode="json")
            json_str = json.dumps(data, indent=2, default=str)

            with open(self.cache_file, "w") as f:
                f.write(json_str)

            logger.debug("News cached successfully", cache_file=str(self.cache_file))

        except Exception as e:
            logger.warning("Failed to save news cache", error=str(e))
