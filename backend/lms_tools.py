from concurrent.futures import Future
import os
from pathlib import Path
from queue import Queue
import re
from threading import Event, Lock, Thread
from urllib.parse import unquote, urlparse

from langchain_core.tools import tool
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

_lms_browser_worker = None
_lms_browser_worker_lock = Lock()


def _course_match_score(query: str, course_name: str) -> int:
    query_words = re.findall(r"[a-z0-9]+", query.lower())
    course_words = re.findall(r"[a-z0-9]+", course_name.lower())
    normalized_query = "".join(query_words)
    normalized_course = "".join(course_words)
    if normalized_query == normalized_course:
        return 100
    if normalized_query in normalized_course:
        return 90
    if normalized_query in course_words:
        return 80
    if len(normalized_query) >= 2:
        for start in range(len(course_words) - len(normalized_query) + 1):
            initials = "".join(
                word[0] for word in course_words[start:start + len(normalized_query)]
            )
            if initials == normalized_query:
                return 70
    return 0


def _select_best_match(query: str, entries: list[dict], item_type: str):
    scored_entries = [
        (score, entry)
        for entry in entries
        if (score := _course_match_score(query, entry["name"]))
    ]
    if not scored_entries:
        available = ", ".join(entry["name"] for entry in entries)
        return None, (
            f'{item_type.title()} "{query}" was not found.'
            + (f" Available {item_type}s: {available}" if available else "")
        )

    highest_score = max(score for score, _ in scored_entries)
    matches = [
        entry for score, entry in scored_entries if score == highest_score
    ]
    if len(matches) > 1:
        choices = ", ".join(entry["name"] for entry in matches)
        return None, (
            f'"{query}" matches multiple {item_type}s: {choices}. '
            "Please specify which one."
        )
    return matches[0], None


class _LmsBrowserWorker:
    def __init__(self):
        self._requests = Queue()
        self._ready = Event()
        self._startup_error = None
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=30):
            raise RuntimeError("Timed out while opening the LMS browser.")
        if self._startup_error:
            raise RuntimeError(
                f"Could not start the LMS browser: {self._startup_error}"
            ) from self._startup_error

    def login(self, person_name: str, username: str, password: str) -> str:
        return self._request(("login", person_name, username, password))

    def select_course(self, course_query: str) -> str:
        return self._request(("select_course", course_query))

    def open_activity(self, operation: str, course_query: str, item_query: str) -> str:
        return self._request((operation, course_query, item_query))

    def _request(self, request) -> str:
        result = Future()
        self._requests.put((request, result))
        return result.result(timeout=90)

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
        except Exception as error:
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()
            self._startup_error = error
            self._ready.set()
            return

        pages = {}
        active_person = None
        self._ready.set()
        try:
            while True:
                request, result = self._requests.get()
                if request is None:
                    break
                if not result.set_running_or_notify_cancel():
                    continue
                try:
                    operation = request[0]
                    if not browser.is_connected():
                        browser = playwright.chromium.launch(headless=False)
                        pages.clear()
                        active_person = None

                    if operation == "login":
                        _, person_name, username, password = request
                        page = pages.get(person_name)
                        if page is None or page.is_closed():
                            page = browser.new_page()
                            pages[person_name] = page

                        if (
                            page.url.startswith("https://lms.nust.edu.pk/")
                            and not page.url.endswith("/login/index.php")
                            and page.locator("#login input#password").count() == 0
                        ):
                            active_person = person_name
                            result.set_result(
                                f"{person_name} is already logged into NUST LMS. "
                                "The Chrome tab has been left open."
                            )
                            continue

                        page.goto(
                            "https://lms.nust.edu.pk/login/index.php",
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
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
                                "LMS did not confirm login within 20 seconds; "
                                "the Chrome tab was left open."
                            ) from error

                        if page.locator("#login input#password").count():
                            error_message = page.locator(
                                "#loginerrormessage, .loginerrors, .alert-danger"
                            ).first
                            if error_message.count() and error_message.is_visible():
                                raise RuntimeError(
                                    f"LMS login failed: {error_message.inner_text().strip()}"
                                )
                            raise RuntimeError(
                                "LMS login did not complete; the login form remains open."
                            )

                        active_person = person_name
                        result.set_result(
                            f"Logged into NUST LMS using the {person_name} account. "
                            "The Chrome tab has been left open."
                        )
                    elif operation == "select_course":
                        _, course_query = request
                        if active_person is None or active_person not in pages:
                            result.set_result(
                                "No LMS account is logged in yet. Log in first, then "
                                "ask me to open the course."
                            )
                            continue

                        page = pages[active_person]
                        course, message = self._open_course(page, course_query)
                        if message:
                            result.set_result(message)
                            continue
                        result.set_result(
                            f'Opened course "{course["name"]}" in the existing '
                            f"{active_person} LMS tab."
                        )
                    elif operation in {
                        "open_quiz",
                        "open_submission",
                        "download_material",
                    }:
                        _, course_query, item_query = request
                        if active_person is None or active_person not in pages:
                            result.set_result(
                                "No LMS account is logged in yet. Log in first, then "
                                "try again."
                            )
                            continue

                        page = pages[active_person]
                        if page.is_closed():
                            pages.pop(active_person, None)
                            active_person = None
                            result.set_result(
                                "The LMS tab was closed. Log in again before continuing."
                            )
                            continue

                        course, message = self._open_course(page, course_query)
                        if message:
                            result.set_result(message)
                            continue

                        if operation == "open_quiz":
                            module_path = "/mod/quiz/"
                            item_type = "quiz"
                        elif operation == "open_submission":
                            module_path = "/mod/assign/"
                            item_type = "submission"
                        else:
                            module_path = "/mod/resource/"
                            item_type = "course file"

                        activities = self._get_course_activities(page, module_path)
                        item, message = _select_best_match(
                            item_query, activities, item_type
                        )
                        if message:
                            result.set_result(
                                f'In course "{course["name"]}": {message}'
                            )
                            continue

                        if operation == "download_material":
                            destination = self._download_course_file(page, item)
                            result.set_result(
                                f'Downloaded "{item["name"]}" from course '
                                f'"{course["name"]}" to {destination}.'
                            )
                            continue

                        page.goto(
                            item["url"],
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                        result.set_result(
                            f'Opened {item_type} "{item["name"]}" in course '
                            f'"{course["name"]}" in the existing LMS tab.'
                        )
                    else:
                        raise ValueError(f"Unknown LMS browser operation: {operation}")
                except Exception as error:
                    result.set_exception(error)
        finally:
            browser.close()
            playwright.stop()

    def _open_course(self, page, course_query: str):
        if page.is_closed():
            return None, "The LMS tab was closed. Log in again before continuing."

        page.goto(
            "https://lms.nust.edu.pk/my/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        if page.locator("#login input#password").count():
            return None, "The LMS session has expired. Log in again before continuing."

        course_links = page.locator('a.coursename[href*="/course/view.php"]')
        try:
            course_links.first.wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            return None, "No courses were found on the LMS dashboard."

        courses = course_links.evaluate_all(
            """links => {
                const seen = new Set();
                return links.flatMap(link => {
                    if (seen.has(link.href)) return [];
                    seen.add(link.href);
                    return [{
                        name: link.querySelector('.multiline')?.innerText?.trim()
                            || link.innerText.replace('Course name', '').trim(),
                        url: link.href
                    }];
                });
            }"""
        )
        course, message = _select_best_match(course_query, courses, "course")
        if message:
            return None, message

        page.goto(course["url"], wait_until="domcontentloaded", timeout=30000)
        return course, None

    def _get_course_activities(self, page, module_path: str) -> list[dict]:
        cards = page.locator('.activity-item[data-region="activity-card"]')
        try:
            cards.first.wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            return []
        return cards.evaluate_all(
            """(cards, modulePath) => cards.flatMap(card => {
                const link = Array.from(card.querySelectorAll('a[href]'))
                    .find(anchor => new URL(anchor.href).pathname.includes(modulePath));
                const name = card.dataset.activityname?.trim();
                return link && name ? [{name, url: link.href}] : [];
            })""",
            module_path,
        )

    def _download_course_file(self, page, activity: dict) -> Path:
        page.goto(activity["url"], wait_until="domcontentloaded", timeout=30000)
        file_links = page.locator(
            'a[href*="/pluginfile.php/"], a[href*="/draftfile.php/"], '
            'a[href*="forcedownload=1"], iframe[src*="/pluginfile.php/"], '
            'object[data*="/pluginfile.php/"], embed[src*="/pluginfile.php/"]'
        )
        direct_url = None
        if file_links.count():
            link = file_links.first
            direct_url = (
                link.get_attribute("href")
                or link.get_attribute("src")
                or link.get_attribute("data")
            )
        elif "/pluginfile.php/" in page.url or "/draftfile.php/" in page.url:
            direct_url = page.url

        if not direct_url:
            raise RuntimeError(
                f'Could not find a downloadable file for "{activity["name"]}" '
                "on the LMS resource page."
            )

        parsed_url = urlparse(direct_url)
        if parsed_url.hostname != "lms.nust.edu.pk":
            raise RuntimeError("Refusing to download a file from an unexpected host.")

        response = page.context.request.get(direct_url, timeout=60000)
        if not response.ok:
            raise RuntimeError(
                f"File download failed with HTTP {response.status}."
            )
        if urlparse(response.url).hostname != "lms.nust.edu.pk":
            raise RuntimeError("The LMS file redirected to an unexpected host.")

        headers = response.headers
        disposition = headers.get("content-disposition", "")
        encoded_filename = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
        plain_filename = re.search(
            r'filename="?([^";]+)"?', disposition, re.I
        )
        if encoded_filename:
            filename = unquote(encoded_filename.group(1))
        elif plain_filename:
            filename = plain_filename.group(1)
        else:
            filename = unquote(Path(parsed_url.path).name)

        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
        if not filename:
            filename = re.sub(r"[^a-zA-Z0-9_-]+", "_", activity["name"]).strip("_")
        if not Path(filename).suffix:
            filename = f"{filename}.download"

        download_dir = Path.home() / "Downloads" / "MyAgent LMS"
        download_dir.mkdir(parents=True, exist_ok=True)
        destination = download_dir / filename
        suffix = destination.suffix
        stem = destination.stem
        counter = 1
        while destination.exists():
            destination = download_dir / f"{stem} ({counter}){suffix}"
            counter += 1
        destination.write_bytes(response.body())
        return destination


def _get_lms_browser_worker() -> _LmsBrowserWorker:
    global _lms_browser_worker
    with _lms_browser_worker_lock:
        if (
            _lms_browser_worker is None
            or not _lms_browser_worker._thread.is_alive()
        ):
            _lms_browser_worker = _LmsBrowserWorker()
        return _lms_browser_worker

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

    return _get_lms_browser_worker().login(normalized_name, username, password)


@tool
def course_selector(course_name: str) -> str:
    """Finds a matching course on the logged-in LMS dashboard and opens it.

    Full or partial course names and abbreviations such as 'DV' are accepted.
    Args:
        course_name: Course title, course code, or abbreviation to find.
    """
    course_query = course_name.strip()
    if not course_query:
        raise ValueError("Course name or abbreviation cannot be empty.")
    if len(course_query) > 120:
        raise ValueError("Course name must be 120 characters or fewer.")
    if not re.search(r"[a-z0-9]", course_query, re.IGNORECASE):
        raise ValueError("Enter a course name, course code, or abbreviation.")

    return _get_lms_browser_worker().select_course(course_query)


@tool
def open_course_quiz(course_name: str, quiz_name: str) -> str:
    """Finds and opens a named quiz within a specific logged-in LMS course.
    Args:
        course_name: Course name, course code, or abbreviation.
        quiz_name: Quiz title or a distinctive part of its title.
    """
    course_query = _validate_lms_item_query(course_name, "Course")
    quiz_query = _validate_lms_item_query(quiz_name, "Quiz")
    return _get_lms_browser_worker().open_activity(
        "open_quiz", course_query, quiz_query
    )


@tool
def open_course_submission(course_name: str, submission_name: str) -> str:
    """Finds and opens a named assignment/submission page within an LMS course.
    Args:
        course_name: Course name, course code, or abbreviation.
        submission_name: Assignment or submission title to open.
    """
    course_query = _validate_lms_item_query(course_name, "Course")
    submission_query = _validate_lms_item_query(submission_name, "Submission")
    return _get_lms_browser_worker().open_activity(
        "open_submission", course_query, submission_query
    )


@tool
def download_course_material(course_name: str, material_name: str) -> str:
    """Downloads a named file/resource from a specific LMS course.
    Args:
        course_name: Course name, course code, or abbreviation.
        material_name: Slide, document, or resource title to download.
    """
    course_query = _validate_lms_item_query(course_name, "Course")
    material_query = _validate_lms_item_query(material_name, "Material")
    return _get_lms_browser_worker().open_activity(
        "download_material", course_query, material_query
    )


def _validate_lms_item_query(value: str, label: str) -> str:
    query = value.strip()
    if not query:
        raise ValueError(f"{label} name cannot be empty.")
    if len(query) > 120:
        raise ValueError(f"{label} name must be 120 characters or fewer.")
    if not re.search(r"[a-z0-9]", query, re.IGNORECASE):
        raise ValueError(f"Enter a valid {label.lower()} name or abbreviation.")
    return query
