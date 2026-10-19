from concurrent.futures import Future
from queue import Queue
from threading import Event, Lock, Thread
from urllib.parse import parse_qs, quote_plus, urlparse

from langchain_core.tools import tool
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

_google_search_worker = None
_google_search_worker_lock = Lock()


def _google_page_has_captcha(page) -> bool:
    if urlparse(page.url).path.startswith("/sorry"):
        return True

    body_text = page.locator("body").inner_text(timeout=5000).lower()
    return (
        "unusual traffic" in body_text
        or "not a robot" in body_text
        or page.locator('iframe[src*="recaptcha"]').count() > 0
    )


def _format_google_results(page, search_query: str) -> str:
    result_nodes = page.locator("#search a:has(h3)").evaluate_all(
        """anchors => anchors.map(anchor => {
            const container = anchor.closest('.MjjYud') || anchor.parentElement?.parentElement;
            return {
                title: anchor.querySelector('h3')?.innerText?.trim() || '',
                url: anchor.href,
                text: container?.innerText?.trim() || ''
            };
        })"""
    )

    results = []
    seen_urls = set()
    for result in result_nodes:
        url = result["url"]
        title = result["title"]
        hostname = urlparse(url).hostname or ""
        if (
            not url.startswith("http")
            or hostname == "google.com"
            or hostname.endswith(".google.com")
            or not title
            or url in seen_urls
        ):
            continue
        seen_urls.add(url)
        snippet = result["text"].replace("\n", " | ")
        if snippet.startswith(title):
            snippet = snippet[len(title):].strip(" |")
        results.append(f"{len(results) + 1}. {title}\n   {url}\n   {snippet}")
        if len(results) == 5:
            break

    if not results:
        return f"Google returned no organic results for: {search_query}"
    return f"Google search results for: {search_query}\n\n" + "\n\n".join(results)


def _search_google_page(page, search_query: str, pending_query: str | None):
    if pending_query and _google_page_has_captcha(page):
        return (
            f"Google requires a CAPTCHA for: {pending_query}. The Chrome tab is still "
            "open. Solve the CAPTCHA in that tab, then ask me to continue the same "
            "search; I will reuse the tab and collect the results.",
            pending_query,
        )

    current_query = parse_qs(urlparse(page.url).query).get("q", [""])[0]
    if current_query != search_query:
        page.goto(
            f"https://www.google.com/search?q={quote_plus(search_query)}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        pending_query = search_query
        if _google_page_has_captcha(page):
            return (
                f"Google requires a CAPTCHA for: {search_query}. A visible Chrome tab "
                "is open. Solve the CAPTCHA in that tab, then ask me to continue the "
                "same search; I will reuse the tab and collect the results.",
                pending_query,
            )

    try:
        page.locator("#search").wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError as error:
        if _google_page_has_captcha(page):
            return (
                f"Google requires a CAPTCHA for: {search_query}. A visible Chrome tab "
                "is open. Solve the CAPTCHA in that tab, then ask me to continue the "
                "same search; I will reuse the tab and collect the results.",
                search_query,
            )
        raise RuntimeError(
            "Google search results did not load in time; the Chrome tab was left open."
        ) from error

    if _google_page_has_captcha(page):
        return (
            f"Google requires a CAPTCHA for: {search_query}. A visible Chrome tab is "
            "open. Solve the CAPTCHA in that tab, then ask me to continue the same "
            "search; I will reuse the tab and collect the results.",
            search_query,
        )

    return _format_google_results(page, search_query), None


class _GoogleSearchBrowser:
    def __init__(self):
        self._requests = Queue()
        self._ready = Event()
        self._startup_error = None
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise RuntimeError("Timed out while opening a visible Chrome search tab.")
        if self._startup_error:
            raise RuntimeError(
                f"Could not start the visible Google search browser: {self._startup_error}"
            ) from self._startup_error

    def search(self, query: str) -> str:
        result = Future()
        self._requests.put((query, result))
        return result.result(timeout=60)

    def _run(self):
        playwright = None
        browser = None
        try:
            playwright = sync_playwright().start()
            try:
                browser = playwright.chromium.launch(headless=False, channel="chrome")
            except PlaywrightError as chrome_error:
                try:
                    browser = playwright.chromium.launch(headless=False)
                except PlaywrightError as chromium_error:
                    raise RuntimeError(
                        f"Could not open Chrome or Playwright Chromium: {chromium_error}"
                    ) from chrome_error

            page = browser.new_page()
        except Exception as error:
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()
            self._startup_error = error
            self._ready.set()
            return

        pending_query = None
        self._ready.set()
        try:
            while True:
                request = self._requests.get()
                if request is None:
                    break
                query, result = request
                if not result.set_running_or_notify_cancel():
                    continue
                try:
                    if not browser.is_connected():
                        browser = playwright.chromium.launch(headless=False)
                        page = browser.new_page()
                        pending_query = None
                    elif page.is_closed():
                        page = browser.new_page()
                        pending_query = None
                    response, pending_query = _search_google_page(
                        page, query, pending_query
                    )
                    result.set_result(response)
                except Exception as error:
                    result.set_exception(error)
        finally:
            browser.close()
            playwright.stop()


def _get_google_search_worker() -> _GoogleSearchBrowser:
    global _google_search_worker
    with _google_search_worker_lock:
        if _google_search_worker is None or not _google_search_worker._thread.is_alive():
            _google_search_worker = _GoogleSearchBrowser()
        return _google_search_worker

@tool
def google_search(query: str) -> str:
    """Searches Google in a visible Chrome tab and returns up to five results.

    If Google presents a CAPTCHA, the tool leaves the tab open for a human to
    solve it. Run the same search again after solving to retrieve the results.

    Args:
        query: What to search for, such as 'live score Pakistan vs India'.
    """
    search_query = query.strip()
    if not search_query:
        raise ValueError("Search query cannot be empty.")
    if len(search_query) > 300:
        raise ValueError("Search query must be 300 characters or fewer.")

    return _get_google_search_worker().search(search_query)
