from django.urls import path

from . import views

app_name = "comments"

urlpatterns = [
    path("", views.index, name="index"),
    path("comments/company", views.company, name="company"),
    path("comments/company/stream", views.company_stream, name="company_stream"),
]
