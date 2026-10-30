"""F603/F604: Selenium으로 토스증권에서 회사 검색 및 커뮤니티 댓글 수집.

토스증권 화면 구조는 바뀔 수 있으므로 셀렉터는 이 파일 상단에 모아 둔다.
"""
import re
import time
from contextlib import contextmanager

from django.conf import settings
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .errors import CompanyNotFound, NoCommentsFound, PipelineError

BASE_URL = "https://www.tossinvest.com"
SEARCH_INPUT = "input[placeholder*='검색']"
STOCK_URL_RE = re.compile(r"/stocks/([A-Za-z0-9]+)")

# 피드 안의 댓글 텍스트(줄바꿈이 보존되는 leaf 요소)를 모은다.
# 클래스명이 난독화되어 있어 계산된 white-space 스타일로 식별한다.
COLLECT_COMMENTS_JS = """
const out = [];
const seen = new Set();
for (const el of document.querySelectorAll('main span, main p, main div')) {
  if (el.children.length > 0) continue;
  const ws = getComputedStyle(el).whiteSpace;
  if (!ws.startsWith('pre')) continue;
  const text = el.innerText.trim();
  if (text && !seen.has(text)) { seen.add(text); out.push(text); }
}
return out;
"""


@contextmanager
def make_driver():
    options = webdriver.ChromeOptions()
    if settings.CRAWL_HEADLESS:
        options.add_argument("--headless=new")
    if settings.CHROME_BINARY:
        options.binary_location = settings.CHROME_BINARY
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--lang=ko-KR")
    from selenium.webdriver.chrome.service import Service

    try:
        if settings.CHROMEDRIVER_PATH:
            driver = webdriver.Chrome(service=Service(settings.CHROMEDRIVER_PATH), options=options)
        else:
            try:
                driver = webdriver.Chrome(options=options)  # Selenium Manager
            except Exception:  # 실패(오프라인 등) 시 webdriver-manager로 재시도
                from webdriver_manager.chrome import ChromeDriverManager

                driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()), options=options
                )
    except Exception as exc:
        raise PipelineError(f"브라우저를 실행하지 못했습니다: {str(exc)[:200]}") from exc
    try:
        yield driver
    finally:
        driver.quit()


def search_company(driver, name, timeout=10):
    """검색창에 회사명을 입력하고 최상단 결과로 이동한다. 종목 코드를 반환."""
    wait = WebDriverWait(driver, timeout)
    driver.get(BASE_URL)
    try:
        box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SEARCH_INPUT)))
        box.click()
        # 클릭 후 열리는 모달의 입력창이 실제 입력 대상이다.
        box = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, SEARCH_INPUT)))
        box.send_keys(name)
        # 검색 결과가 뜨면 최상단 항목이 자동 포커스되므로 Enter로 선택한다.
        wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "a[href*='/stocks/']"))
        time.sleep(0.5)
        box.send_keys(Keys.ENTER)
        wait.until(EC.url_matches(r"/stocks/[A-Za-z0-9]+"))
    except TimeoutException as exc:
        raise CompanyNotFound(f"'{name}'에 대한 검색 결과가 없습니다.") from exc
    match = STOCK_URL_RE.search(driver.current_url)
    if not match:
        raise CompanyNotFound(f"'{name}'에 대한 검색 결과가 없습니다.")
    return match.group(1)


def stock_name(driver, fallback):
    """상세 페이지 헤더에서 실제 종목명을 읽는다."""
    for css in ("h1", "[data-contents-label='stock-name']"):
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            if el.text.strip():
                return el.text.strip()
    title = driver.title.split("·")[0].split("-")[0].strip()
    return title or fallback


def collect_comments(driver, code, limit, timeout=10):
    """커뮤니티 탭으로 이동해 스크롤하며 댓글을 limit개까지 수집한다."""
    driver.get(f"{BASE_URL}/stocks/{code}/community")
    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(lambda d: d.execute_script(COLLECT_COMMENTS_JS))
    except TimeoutException as exc:
        raise NoCommentsFound("커뮤니티에 댓글이 존재하지 않습니다.") from exc

    comments = []
    for _ in range(15):
        comments = driver.execute_script(COLLECT_COMMENTS_JS)
        if len(comments) >= limit:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)
    if not comments:
        raise NoCommentsFound("커뮤니티에 댓글이 존재하지 않습니다.")
    return comments[:limit]


def crawl(name, on_progress=None):
    """(실제종목명, 댓글 리스트) 반환. 실패 시 PipelineError 계열 예외."""
    notify = on_progress or (lambda msg: None)
    with make_driver() as driver:
        notify("토스증권에서 회사를 검색하는 중...")
        code = search_company(driver, name)
        official = stock_name(driver, name)
        notify(f"'{official}' 커뮤니티 댓글을 수집하는 중...")
        comments = collect_comments(driver, code, settings.CRAWL_COMMENT_LIMIT)
    return official, comments
