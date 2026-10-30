# 05-pjt · 댓글 증강 시스템 (Django + Selenium + GMS LLM)

회사명을 입력하면 토스증권 커뮤니티 댓글을 실시간 크롤링하고, 전처리 → LLM 증강 → 요약까지
한 화면에 보여주는 Django 웹 서비스입니다.

## 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env        # .env 를 열어 GMS_API_KEY=발급받은키 로 수정 (서버 재시작 필요)
python manage.py migrate
python manage.py runserver
```

http://127.0.0.1:8000/ 접속 → 회사명 입력(예: `삼성`). Chrome이 설치되어 있어야 합니다.
옵션 환경변수: `CRAWL_HEADLESS=1`(창 없이 실행, 기본은 창 표시), `CHROME_BINARY`, `CHROMEDRIVER_PATH`, `GMS_MODEL`.

테스트: `python manage.py test` (크롤러/LLM은 mock 처리)

## 요구사항 구현 현황

| 번호 | 내용 | 구현 위치 |
|---|---|---|
| F601 | 회사명 입력·검증 (빈 값이면 무동작, 입력 시 터미널 출력) | `views.company`, `index.html` |
| F602 | DB 스키마 (실제종목명, 원본/정제/증강 댓글, IQR 정보, 생성일시) + 마이그레이션 | `models.CommentAnalysis` |
| F603 | 검색 후 최상단 회사 자동 선택, 스트리밍으로 진행 상황 출력(선택) | `services/crawler.search_company`, `views.company_stream` |
| F604 | 커뮤니티 탭 이동 후 댓글 20개 수집 | `services/crawler.collect_comments` |
| F605 | 길이(5~76) · 특수문자/ㅋㅋㅋ 제거 · LLM 부적절 댓글 제거 | `services/preprocess.py`, `llm.find_inappropriate` |
| F606 | 의미를 유지한 댓글 증강 | `llm.augment` |
| F607 | 원본/전처리/증강/최종 결과를 4단 화면 출력 및 DB 저장 | `_results.html`, `services/pipeline.py` |
| F610 (심화) | 전체 댓글 요약을 화면 하단에 출력 | `llm.summarize` |
| F611 (심화) | 검색 결과·댓글 없음, API 오류 등 안내 메시지 | `services/errors.py`, `pipeline.run` |

## 설계 메모

- 입력 → 처리 → 출력 흐름을 `services/pipeline.run()` 제너레이터 하나로 묶어, 일반 요청
  (`/comments/company`)과 스트리밍 요청(`/comments/company/stream`, NDJSON)이 로직을 공유합니다.
- 최종 결과 = 정제 댓글 + 증강 댓글. IQR 통계(Q1/Q3/경계값)는 원본 댓글 길이 기준으로 계산해 저장하며,
  실제 필터링은 명세의 5~76자 고정 기준을 사용합니다.
- 크롤링 셀렉터는 `services/crawler.py` 상단에 모아 두었습니다.

## 알려진 한계 (솔직한 메모)

- 개발 환경에서 토스증권 접속이 차단되어 **실제 사이트 대상 크롤링은 검증하지 못했습니다.**
  검색창/댓글 영역 셀렉터는 사이트 구조(명세 그림 3~6)에 따른 추정이므로, 동작하지 않으면
  `SEARCH_INPUT`, `COLLECT_COMMENTS_JS`를 개발자도구로 확인해 수정해야 합니다.
- GMS 호출도 키가 없어 실제 호출은 하지 않았고, 응답 파싱은 mock 테스트로만 확인했습니다.

## 학습 내용 / 느낀 점

- 동적 페이지 크롤링은 대기(WebDriverWait)와 스크롤 처리가 핵심이며, 난독화된 클래스명 대신
  구조·스타일 기반으로 요소를 찾는 방법을 고민했습니다.
- LLM 응답은 형식이 흔들리므로 JSON 파싱을 방어적으로 작성하고 개수 검증이 필요했습니다.
- 외부 의존(크롤러, LLM)을 서비스 계층으로 분리하니 mock 기반 테스트가 쉬워졌습니다.
