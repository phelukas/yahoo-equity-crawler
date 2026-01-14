from __future__ import annotations

from dataclasses import dataclass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions


@dataclass(frozen=True)
class DriverConfig:
    headless: bool = True
    page_load_timeout: int = 30


def create_chrome_driver(cfg: DriverConfig) -> webdriver.Chrome:
    options = ChromeOptions()

    # headless moderno (Chrome >= 109)
    if cfg.headless:
        options.add_argument("--headless=new")

    # padrões estáveis para container/CI e evitar travas
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(cfg.page_load_timeout)
    return driver
 
