from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait


def wait(driver: WebDriver, timeout: int = 20) -> WebDriverWait:
    return WebDriverWait(driver, timeout)
