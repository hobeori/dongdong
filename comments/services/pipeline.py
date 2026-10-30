"""입력 -> 크롤링 -> 전처리 -> 증강 -> 요약 -> 저장 파이프라인.

단계마다 이벤트를 yield 하므로 스트리밍 뷰와 일반 뷰가 같은 로직을 재사용한다.
진행 단계(step): search, collect, clean, augment, summarize
"""
from . import crawler, llm, preprocess
from .errors import LLMError, NoCommentsFound, PipelineError
from ..models import CommentAnalysis


def _progress(step, message):
    return {"type": "progress", "step": step, "message": message}


def run(company_name):
    try:
        yield _progress("search", "크롤링을 시작합니다...")
        official, raw = None, []
        for event in crawler.crawl_events(company_name):
            if event["type"] == "progress":
                yield event
            else:
                official, raw = event["official"], event["comments"]

        yield _progress("clean", f"댓글 {len(raw)}개를 전처리하는 중...")
        warnings = []

        def best_effort(step, func, default):
            """LLM 단계가 실패해도 크롤링 결과는 보여주기 위해 경고만 남긴다."""
            try:
                return func()
            except LLMError as exc:
                warnings.append(f"{step} 단계를 건너뜀: {exc}")
                return default

        iqr = preprocess.iqr_info(raw)
        ruled = preprocess.apply_rules(raw)
        kept_idx = [i for i, c in enumerate(ruled) if c is not None]
        candidates = [ruled[i] for i in kept_idx]
        bad = best_effort("부적절 댓글 필터링", lambda: llm.find_inappropriate(candidates), set())

        status = ["kept" if c is not None else "rule" for c in ruled]
        for j in bad:
            status[kept_idx[j]] = "llm"
        cleaned = [c for j, c in enumerate(candidates) if j not in bad]
        if not cleaned:
            raise NoCommentsFound("전처리 후 남은 댓글이 없습니다.")

        yield _progress("augment", f"댓글 {len(cleaned)}개를 증강하는 중...")
        augmented = best_effort("댓글 증강", lambda: llm.augment(cleaned), [])

        yield _progress("summarize", "댓글을 요약하는 중...")
        summary = best_effort("댓글 요약", lambda: llm.summarize(raw), "")

        analysis = CommentAnalysis.objects.create(
            query_name=company_name,
            stock_name=official,
            raw_comments=raw,
            raw_status=status,
            cleaned_comments=cleaned,
            augmented_comments=augmented,
            iqr_info=iqr,
            summary=summary,
        )
        yield {"type": "result", "analysis": analysis, "warnings": list(dict.fromkeys(warnings))}
    except PipelineError as exc:
        yield {"type": "error", "message": str(exc)}
    except Exception:  # 예상치 못한 오류도 화면에서 안내한다.
        yield {"type": "error", "message": "처리 중 알 수 없는 오류가 발생했습니다."}
        raise
