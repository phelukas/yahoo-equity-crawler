import logging


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # “Corta” barulho de libs
    noisy = [
        "selenium",
        "urllib3",
        "websocket",
        "WDM",  # se usar webdriver-manager
    ]
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Se quiser ainda mais limpo:
    logging.getLogger("selenium.webdriver.common.selenium_manager").setLevel(
        logging.ERROR
    )
