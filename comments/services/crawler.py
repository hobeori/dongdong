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
SEARCH_INPUT = "input[placeholder*='검색'], button[aria-label*='검색']"
STOCK_URL_RE = re.compile(r"/stocks/([A-Za-z0-9]+)")

# 커뮤니티 피드의 텍스트를 화면 위치 기준으로 모은다.
# 클래스명이 난독화되어 있어 DOM 구조 대신 "인기순/최신순 정렬 버튼 아래, 주문 패널 왼쪽"
# 영역의 leaf 텍스트를 읽는다. 작성자명(시간 표기 바로 앞), 시간, 숫자, 버튼 문구는 제외한다.
COLLECT_COMMENTS_JS = """
// 텍스트 노드 단위로 읽는다 (아이콘이 같이 들어있는 버튼도 텍스트를 가진다).
const byParent = new Map();
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
while (walker.nextNode()) {
  const n = walker.currentNode;
  const t = n.nodeValue.trim();
  if (!t) continue;
  const tag = n.parentElement && n.parentElement.tagName;
  if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') continue;
  const range = document.createRange();
  range.selectNodeContents(n);
  const r = range.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) continue;
  const key = n.parentElement;
  let fixed = false;  // 하단 시세 바, 사이드바 같은 고정 영역은 댓글이 아니다
  for (let e = key; e && e !== document.body; e = e.parentElement) {
    const pos = getComputedStyle(e).position;
    if (pos === 'fixed' || pos === 'sticky') { fixed = true; break; }
  }
  if (fixed) continue;
  if (byParent.has(key)) { byParent.get(key).t += ' ' + t; }
  else byParent.set(key, {t, left: r.left + window.scrollX, right: r.right + window.scrollX,
                          top: r.top + window.scrollY, vbottom: r.bottom});
}
const leaves = [...byParent.values()];
const find = (re) => leaves.find(l => re.test(l.t) && l.t.length < 12);
const sort = find(/^(인기순|최신순)$/);
const order = find(/^주문하기$/);
const rightLimit = order ? order.left - 10 : Infinity;
// 내부 스크롤로 기준점이 밀리지 않도록 처음 찾은 위치를 고정한다.
if (window.__feedTop === undefined && sort) window.__feedTop = sort.top + 5;
const topLimit = window.__feedTop !== undefined ? window.__feedTop : 250;
if (window.__feedLeft === undefined && sort) window.__feedLeft = sort.left - 20;
const leftLimit = window.__feedLeft !== undefined ? window.__feedLeft : 0;
// 화면 하단의 시세 바("투자 유의사항 ... 달러 인덱스 ...") 위까지만 피드로 본다.
const footer = leaves.find(l => /^투자 유의사항$/.test(l.t));
const bottomLimit = footer ? footer.top - window.scrollY - 2 : window.innerHeight - 50;
const feed = leaves.filter(l => l.top > topLimit && l.left >= leftLimit && l.right <= rightLimit
                                && l.vbottom <= bottomLimit);
const TIME = /^\\d+\\s*(초|분|시간|일)(\\s*전)?(\\s*[^\\w가-힣\\s]?\\s*팔로워\\s*[\\d,.]+[만천]?)?$/;
const SKIP = /^(팔로우|팔로잉|주주|\\d+|인기순|최신순|의견 남기기|전체 보기|실시간|오늘 시장 어떻게 보세요\\?)$/;
const out = [], seen = new Set();
feed.forEach((l, i) => {
  if (SKIP.test(l.t) || TIME.test(l.t)) return;
  const next = feed[i + 1];
  if (next && TIME.test(next.t)) return;  // 작성자명
  if (!seen.has(l.t)) { seen.add(l.t); out.push(l.t); }
});
return out;
"""

SCROLL_JS = """
// 중간 댓글을 건너뛰지 않도록 화면 높이의 60%씩 내린다.
window.scrollBy(0, window.innerHeight * 0.6);
for (const el of document.querySelectorAll('*')) {
  const oy = getComputedStyle(el).overflowY;
  if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 20) {
    el.scrollTop += el.clientHeight * 0.6;
  }
}
"""

# 상세 페이지 헤더는 "삼성전자 005930" 형태다.
STOCK_HEADER_JS = """
for (const el of document.querySelectorAll('span, div, h1, h2')) {
  const t = el.innerText ? el.innerText.trim() : '';
  if (t.length > 40) continue;
  const m = t.match(/^(.+?)\\s+[0-9A-Z]{6}$/);
  if (m) return m[1].trim();
}
return '';
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
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    if settings.CRAWL_HEADLESS:  # headless UA에는 "HeadlessChrome"이 들어가 차단될 수 있다
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
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


def _dump_debug(driver, step):
    """실패 시 화면과 HTML을 저장해 셀렉터를 확인할 수 있게 한다."""
    try:
        out = settings.BASE_DIR / "crawl_debug"
        out.mkdir(exist_ok=True)
        driver.save_screenshot(str(out / f"{step}.png"))
        (out / f"{step}.html").write_text(driver.page_source, encoding="utf-8")
        print(f"[crawler] '{step}' 단계 실패 - 디버그 파일 저장: {out}")
    except Exception:
        pass


# 최초 접속 시 뜨는 안내 말풍선/배너의 닫기 버튼을 누른다.
DISMISS_POPUPS_JS = """
let n = 0;
for (const el of document.querySelectorAll('[aria-label*="닫"], [aria-label*="close" i], button')) {
  const label = (el.getAttribute('aria-label') || '') + (el.innerText || '');
  if (/닫|close|^[×✕xX]$/i.test(label.trim()) && el.offsetParent !== null) { el.click(); n++; }
}
// "요즘 어디로 돈이..." 같은 말풍선: 텍스트를 포함한 가장 가까운 컨테이너의 마지막 버튼
const tip = [...document.querySelectorAll('div')].find(
  d => d.innerText && d.innerText.includes('보여요') && d.innerText.length < 120 && d.querySelector('button, svg'));
if (tip) { const b = tip.querySelector('button') || tip.querySelector('svg'); if (b) { b.dispatchEvent(new MouseEvent('click', {bubbles: true})); n++; } }
return n;
"""

MODAL_INPUT = "input[placeholder*='검색어']"


def _visible(driver, css):
    for el in driver.find_elements(By.CSS_SELECTOR, css):
        if el.is_displayed():
            return el
    return None


def _open_search_modal(driver, wait):
    """검색 모달을 열고 모달의 입력창을 반환한다."""
    driver.get(BASE_URL)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(2)
    for _ in range(2):  # 온보딩 팝업이 클릭/단축키를 가로채므로 먼저 닫는다
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        driver.execute_script(DISMISS_POPUPS_JS)
        time.sleep(0.5)
    # 여러 방법을 차례로 시도: 일반 클릭 -> JS 클릭 -> "/" 단축키
    attempts = (
        lambda el: el.click(),
        lambda el: driver.execute_script("arguments[0].click();", el),
    )
    for el in driver.find_elements(By.CSS_SELECTOR, SEARCH_INPUT):
        for attempt in attempts:
            try:
                attempt(el)
            except WebDriverException:
                continue
            time.sleep(1)
            box = _visible(driver, MODAL_INPUT)
            if box:
                return box
    driver.find_element(By.TAG_NAME, "body").send_keys("/")
    return wait.until(lambda d: _visible(d, MODAL_INPUT))


def search_company(driver, name, timeout=10):
    """검색창에 회사명을 입력하고 최상단 결과로 이동한다. 종목 코드를 반환."""
    wait = WebDriverWait(driver, timeout)
    step = "open_search"
    try:
        box = _open_search_modal(driver, wait)
        step = "type_and_select"
        box.send_keys(name)
        time.sleep(2)  # 검색 결과가 뜰 때까지 대기 (최상단 항목이 자동 포커스됨)
        box.send_keys(Keys.ENTER)
        try:
            wait.until(EC.url_matches(r"/stocks/[A-Za-z0-9]+"))
        except TimeoutException:  # 자동 포커스가 없었다면 첫 항목으로 직접 이동
            box.send_keys(Keys.ARROW_DOWN)
            box.send_keys(Keys.ENTER)
            wait.until(EC.url_matches(r"/stocks/[A-Za-z0-9]+"))
    except TimeoutException as exc:
        _dump_debug(driver, step)
        if step == "open_search":
            raise PipelineError(
                "토스증권 검색창을 열지 못했습니다 (crawl_debug 폴더 확인)."
            ) from exc
        raise CompanyNotFound(f"'{name}'에 대한 검색 결과가 없습니다.") from exc
    match = STOCK_URL_RE.search(driver.current_url)
    if not match:
        raise CompanyNotFound(f"'{name}'에 대한 검색 결과가 없습니다.")
    return match.group(1)


def stock_name(driver, fallback):
    """상세 페이지 헤더("삼성전자 005930")에서 실제 종목명을 읽는다."""
    try:
        WebDriverWait(driver, 5).until(lambda d: d.execute_script(STOCK_HEADER_JS))
    except TimeoutException:
        return fallback
    return driver.execute_script(STOCK_HEADER_JS) or fallback


def collect_comments(driver, code, limit, timeout=10):
    """커뮤니티 탭으로 이동해 스크롤하며 댓글을 limit개까지 수집한다."""
    driver.get(f"{BASE_URL}/stocks/{code}/community")
    wait = WebDriverWait(driver, timeout)
    try:
        wait.until(lambda d: d.execute_script(COLLECT_COMMENTS_JS))
    except TimeoutException as exc:
        _dump_debug(driver, "community")
        raise NoCommentsFound("커뮤니티에 댓글이 존재하지 않습니다.") from exc

    comments, stale = [], 0
    for _ in range(40):
        before = len(comments)
        for text in driver.execute_script(COLLECT_COMMENTS_JS):  # 스크롤하며 누적
            if text not in comments:
                comments.append(text)
        stale = stale + 1 if len(comments) == before else 0
        if len(comments) >= limit or stale >= 4:
            break
        driver.execute_script(SCROLL_JS)  # 내부 스크롤 영역까지 내린다
        time.sleep(1)
    if not comments:
        raise NoCommentsFound("커뮤니티에 댓글이 존재하지 않습니다.")
    return comments[:limit]


def crawl_events(name):
    """진행 이벤트를 yield 하고, 마지막에 {"type": "crawled", ...} 를 yield 한다.

    실패 시 PipelineError 계열 예외를 던진다.
    """
    with make_driver() as driver:
        yield {"type": "progress", "step": "search", "message": "토스증권에서 회사를 검색하는 중..."}
        code = search_company(driver, name)
        official = stock_name(driver, name)
        yield {
            "type": "progress",
            "step": "collect",
            "message": f"'{official}' 커뮤니티 댓글을 수집하는 중...",
        }
        comments = collect_comments(driver, code, settings.CRAWL_COMMENT_LIMIT)
    yield {"type": "crawled", "official": official, "comments": comments}
