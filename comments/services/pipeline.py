"""입력 -> 크롤링 -> 전처리 -> 증강 -> 요약 -> 저장 파이프라인.

단계마다 이벤트를 yield 하므로 스트리밍 뷰와 일반 뷰가 같은 로직을 재사용한다.
"""
from . import crawler, llm, preprocess
from .errors import NoCommentsFound, PipelineError
from ..models import CommentAnalysis


def run(company_name):
    try:
        yield {"type": "progress", "message": "크롤링을 시작합니다..."}
        messages = []
        official, raw = crawler.crawl(company_name, on_progress=messages.append)
        for m in messages:
            yield {"type": "progress", "message": m}

        yield {"type": "progress", "message": f"댓글 {len(raw)}개 전처리 중..."}
        iqr = preprocess.iqr_info(raw)
        cleaned = preprocess.filter_by_rules(raw)
        bad = llm.find_inappropriate(cleaned)
        cleaned = [c for i, c in enumerate(cleaned) if i not in bad]
        if not cleaned:
            raise NoCommentsFound("전처리 후 남은 댓글이 없습니다.")

        yield {"type": "progress", "message": f"댓글 {len(cleaned)}개를 증강하는 중..."}
        augmented = llm.augment(cleaned)

        yield {"type": "progress", "message": "댓글을 요약하는 중..."}
        summary = llm.summarize(raw)

        analysis = CommentAnalysis.objects.create(
            query_name=company_name,
            stock_name=official,
            raw_comments=raw,
            cleaned_comments=cleaned,
            augmented_comments=augmented,
            iqr_info=iqr,
            summary=summary,
        )
        yield {"type": "result", "analysis": analysis}
    except PipelineError as exc:
        yield {"type": "error", "message": str(exc)}
    except Exception:  # 예상치 못한 오류도 화면에서 안내한다.
        yield {"type": "error", "message": "처리 중 알 수 없는 오류가 발생했습니다."}
        raise
