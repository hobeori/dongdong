from django.contrib import admin

from .models import CommentAnalysis


@admin.register(CommentAnalysis)
class CommentAnalysisAdmin(admin.ModelAdmin):
    list_display = ("stock_name", "query_name", "created_at")
    search_fields = ("stock_name", "query_name")
