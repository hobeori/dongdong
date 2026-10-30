"""F605: 댓글 전처리 (길이 필터 · 특수문자/불필요 패턴 제거 · IQR 통계)."""
import re

from django.conf import settings

_JAMO = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]+")  # ㅋㅋㅋ, ㅠㅠ 같은 자음/모음 반복
_SPECIAL = re.compile(r"[^0-9A-Za-z가-힣\s]")
_SPACES = re.compile(r"\s+")


def clean_text(text):
    """자음/모음 패턴과 특수문자를 제거하고 공백을 정리한다."""
    text = _JAMO.sub(" ", text or "")
    text = _SPECIAL.sub("", text)
    return _SPACES.sub(" ", text).strip()


def apply_rules(comments, min_len=None, max_len=None):
    """원본과 같은 순서로, 규칙을 통과한 댓글은 정제된 문자열을, 제거된 댓글은 None을 돌려준다.

    길이 상한은 원문 기준, 하한은 정제 후 기준으로 검사한다.
    """
    min_len = settings.COMMENT_MIN_LEN if min_len is None else min_len
    max_len = settings.COMMENT_MAX_LEN if max_len is None else max_len
    result = []
    for comment in comments:
        if not isinstance(comment, str) or not comment.strip() or len(comment.strip()) > max_len:
            result.append(None)
            continue
        cleaned = clean_text(comment)
        result.append(cleaned if len(cleaned) >= min_len else None)
    return result


def filter_by_rules(comments, min_len=None, max_len=None):
    """결측치, 너무 짧거나 긴 댓글, 정제 후 의미가 없어진 댓글을 제거한 정제 목록."""
    return [c for c in apply_rules(comments, min_len, max_len) if c is not None]


def _quantile(sorted_values, q):
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def iqr_info(comments):
    """원본 댓글 길이의 IQR 통계 (참고용으로 DB에 저장)."""
    lengths = sorted(len(c) for c in comments if isinstance(c, str))
    info = {
        "min_len": settings.COMMENT_MIN_LEN,
        "max_len": settings.COMMENT_MAX_LEN,
    }
    if not lengths:
        return info
    q1, q3 = _quantile(lengths, 0.25), _quantile(lengths, 0.75)
    iqr = q3 - q1
    info.update(
        q1=q1,
        q3=q3,
        iqr=iqr,
        lower_bound=q1 - 1.5 * iqr,
        upper_bound=q3 + 1.5 * iqr,
    )
    return info
