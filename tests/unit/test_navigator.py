from selenium.common.exceptions import TimeoutException

from yahoo_crawler.infrastructure.yahoo.navigator import YahooNavigator


class TimeoutDriver:
    current_url = "https://finance.yahoo.com/research-hub/screener/equity/?region=AR"
    stopped = False

    def get(self, url: str) -> None:
        self.current_url = url
        raise TimeoutException("renderer timeout")

    def execute_script(self, script: str):
        if script == "window.stop();":
            self.stopped = True
            return None
        return "interactive"

    def find_elements(self, *args):
        return []


def test_open_continues_when_dom_is_available_after_page_timeout() -> None:
    driver = TimeoutDriver()

    YahooNavigator(driver, timeout=1).open("Argentina")

    assert driver.stopped is True
    assert "region=AR" in driver.current_url
