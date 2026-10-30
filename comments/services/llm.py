"""GMS(LLM) 호출: 부적절 댓글 필터링(F605), 증강(F606), 요약(F610)."""
import json
import re

import requests
from django.conf import settings

from .errors import LLMError


def chat(prompt, system=None):
    if not settings.GMS_API_KEY:
        raise LLMError("GMS_API_KEY가 설정되지 않았습니다. .env 또는 환경변수를 확인하세요.")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = requests.post(
            settings.GMS_API_URL,
            headers={"Authorization": f"Bearer {settings.GMS_API_KEY}"},
            json={"model": settings.GMS_MODEL, "messages": messages},
            timeout=settings.GMS_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"LLM 호출에 실패했습니다: {exc}") from exc


def parse_json_array(text):
    """응답에서 JSON 배열을 추출한다 (코드블록/잡설이 섞여 있어도 동작)."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise LLMError("LLM 응답에서 JSON 배열을 찾지 못했습니다.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM 응답을 해석하지 못했습니다: {exc}") from exc
    return data


def _numbered(comments):
    return "\n".join(f"{i}. {c}" for i, c in enumerate(comments))


def find_inappropriate(comments):
    """부적절한 댓글의 인덱스(0부터) 집합을 반환한다."""
    if not comments:
        return set()
    prompt = (
        "다음 댓글 목록에서 부적절한 댓글(욕설, 혐오, 비방, 선정성, 과도한 비난 등)의 "
        "번호(0부터 시작)만 JSON 배열로 알려줘. 없으면 []만 출력해.\n\n" + _numbered(comments)
    )
    data = parse_json_array(chat(prompt))
    return {i for i in data if isinstance(i, int) and 0 <= i < len(comments)}


def augment(comments):
    """각 댓글의 의미를 유지한 채 확장한 문장을 같은 순서로 반환한다."""
    if not comments:
        return []
    prompt = (
        "다음 댓글들을 각각 원래 의미를 유지하면서 자연스럽고 조금 더 풍부한 한 문장으로 "
        "확장해줘. 입력과 같은 개수, 같은 순서의 문자열 JSON 배열만 출력해.\n\n"
        + _numbered(comments)
    )
    data = parse_json_array(chat(prompt))
    result = [str(x).strip() for x in data if isinstance(x, (str, int, float)) and str(x).strip()]
    if len(result) != len(comments):
        raise LLMError(
            f"증강 결과 개수가 맞지 않습니다 (입력 {len(comments)}개, 응답 {len(result)}개)."
        )
    return result


def summarize(comments):
    if not comments:
        return ""
    prompt = (
        "다음은 주식 커뮤니티 댓글이다. 투자자들의 주요 의견과 분위기를 "
        "3~4문장의 한국어로 요약해줘.\n\n" + "\n".join(f"- {c}" for c in comments)
    )
    return chat(prompt)
