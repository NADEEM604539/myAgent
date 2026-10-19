import platform
import datetime
import os
import re

from langchain_core.tools import tool
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

_lms_browser_sessions = []

@tool
def get_system_info() -> str:
    """Returns the host machine operating system, release, and architecture details."""
    return f"OS: {platform.system()} {platform.release()} ({platform.machine()})"

@tool
def get_current_time() -> str:
    """Returns current date and time in ISO format."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def execute_calculator(expression: str) -> str:
    """Evaluates mathematical operations safely.
    Args:
        expression: A math expression string like '128 * 45 / 3'
    """
    try:
        allowed = {"__builtins__": None}
        result = eval(expression, allowed, {})
        return f"Calculation Result: {result}"
    except Exception as e:
        return f"Math Evaluation Error: {str(e)}"

@tool
def login_to_lms(person_name: str = "NADEEM") -> str:
    """Opens a visible Chrome tab and signs in using name-specific environment variables.
    Args:
        person_name: Account name prefix, such as 'NADEEM' or 'BILAL'.
    """
    normalized_name = person_name.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", normalized_name):
        raise ValueError("Person name must start with a letter and contain only letters, numbers, or underscores.")

    username_key = f"{normalized_name}_LMS_USERNAME"
    password_key = f"{normalized_name}_LMS_PASSWORD"
    username = os.getenv(username_key)
    password = os.getenv(password_key)
    missing_keys = [
        key for key, value in ((username_key, username), (password_key, password))
        if not value
    ]
    if missing_keys:
        raise ValueError(f"Missing required environment variable(s): {', '.join(missing_keys)}.")

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(headless=False, channel="chrome")
    except PlaywrightError as chrome_error:
        try:
            browser = playwright.chromium.launch(headless=False)
        except PlaywrightError as chromium_error:
            playwright.stop()
            raise RuntimeError(
                f"Could not open Chrome or Playwright Chromium: {chromium_error}"
            ) from chrome_error

    page = browser.new_page()
    _lms_browser_sessions.append((playwright, browser, page))
    login_url = "https://lms.nust.edu.pk/login/index.php"
    page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

    username_field = page.locator("#login input#username")
    password_field = page.locator("#login input#password")
    username_field.wait_for(state="visible", timeout=15000)
    password_field.wait_for(state="visible", timeout=15000)
    username_field.fill(username, timeout=10000)
    password_field.fill(password, timeout=10000)
    page.locator("#login button[type='submit']").click(timeout=10000)

    try:
        page.wait_for_function(
            """() => window.location.pathname !== '/login/index.php'
                || Boolean(document.querySelector(
                    '#loginerrormessage, .loginerrors, .alert-danger'
                ))""",
            timeout=20000,
        )
    except PlaywrightTimeoutError as error:
        raise RuntimeError(
            "LMS did not confirm login within 20 seconds; the Chrome tab was left open."
        ) from error

    if page.locator("#login input#password").count():
        error_message = page.locator(
            "#loginerrormessage, .loginerrors, .alert-danger"
        ).first
        if error_message.count() and error_message.is_visible():
            raise RuntimeError(f"LMS login failed: {error_message.inner_text().strip()}")
        raise RuntimeError(
            "LMS login did not complete; the login form remains open in Chrome."
        )

    return (
        f"Logged into NUST LMS using the {normalized_name} account. "
        "The Chrome tab has been left open."
    )

# List of all tools registered for the LangGraph agent
ALL_TOOLS = [get_system_info, get_current_time, execute_calculator, login_to_lms]