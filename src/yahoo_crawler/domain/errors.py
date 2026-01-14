class CrawlerError(RuntimeError):
    """Exceção base para erros do crawler."""


class ParseError(CrawlerError):
    """Lançada quando a estrutura HTML não é a esperada."""


class NavigationError(CrawlerError):
    """Lançada quando a navegação/filtragem do Selenium falha."""
