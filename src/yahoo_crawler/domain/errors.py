class CrawlerError(RuntimeError):
    """Base exception for crawler errors."""


class ParseError(CrawlerError):
    """Raised when HTML structure is not as expected."""


class NavigationError(CrawlerError):
    """Raised when Selenium navigation/filtering fails."""
