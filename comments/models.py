from django.db import models


class CommentAnalysis(models.Model):
    """한 번의 크롤링 요청에서 단계별로 생성된 결과 (F602, F607)."""

    query_name = models.CharField("검색어", max_length=100)
    stock_name = models.CharField("실제종목명", max_length=100)
    raw_comments = models.JSONField("원본 댓글 목록", default=list)
    cleaned_comments = models.JSONField("정제 댓글 목록", default=list)
    augmented_comments = models.JSONField("증강 댓글 목록", default=list)
    iqr_info = models.JSONField("IQR 임계값 정보", default=dict)
    summary = models.TextField("댓글 요약", blank=True, default="")
    created_at = models.DateTimeField("생성 일시", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.stock_name} ({self.created_at:%Y-%m-%d %H:%M})"

    @property
    def final_comments(self):
        """통합 결과: 정제 댓글 + 증강 댓글."""
        return list(self.cleaned_comments) + list(self.augmented_comments)
