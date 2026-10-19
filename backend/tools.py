import datetime
import platform

from langchain_core.tools import tool
from backend.google_search_tools import google_search
from backend.lms_tools import (
    course_selector,
    download_course_material,
    login_to_lms,
    open_course_quiz,
    open_course_submission,
)


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

ALL_TOOLS = [
    get_system_info,
    get_current_time,
    execute_calculator,
    login_to_lms,
    course_selector,
    open_course_quiz,
    open_course_submission,
    download_course_material,
    google_search,
]
