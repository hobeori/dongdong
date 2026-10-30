import json

from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string

from .services import pipeline


def _clean_name(request):
    return request.GET.get("company_name", "").strip()


def index(request):
    return render(request, "comments/index.html")


def company(request):
    """F601: 회사명 입력 검증. 값이 없으면 아무 동작도 하지 않는다."""
    name = _clean_name(request)
    if not name:
        return render(request, "comments/index.html")
    print(name)  # 요구사항: 입력된 회사명을 VS Code 터미널에 출력

    context = {"company_name": name}
    for event in pipeline.run(name):
        if event["type"] == "result":
            context["analysis"] = event["analysis"]
            context["warnings"] = event["warnings"]
        elif event["type"] == "error":
            context["error"] = event["message"]
    return render(request, "comments/index.html", context)


def company_stream(request):
    """크롤링 진행 상황을 NDJSON으로 스트리밍한다 (선택 기능)."""
    name = _clean_name(request)
    if not name:
        return StreamingHttpResponse(iter(()), content_type="application/x-ndjson", status=400)
    print(name)

    def events():
        for event in pipeline.run(name):
            if event["type"] == "result":
                html = render_to_string(
                    "comments/_results.html", {"analysis": event["analysis"], "warnings": event["warnings"]}, request
                )
                event = {"type": "result", "html": html}
            yield json.dumps(event, ensure_ascii=False) + "\n"

    response = StreamingHttpResponse(events(), content_type="application/x-ndjson")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
