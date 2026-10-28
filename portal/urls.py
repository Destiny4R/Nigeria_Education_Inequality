from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("methodology/", views.methodology, name="methodology"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("inequality/", views.inequality, name="inequality"),
    path("inequality/export.csv", views.inequality_export, name="inequality_export"),
    path("data/", views.data_home, name="data_home"),
    path("data/dictionary/", views.dictionary, name="dictionary"),
    path("data/dataset/<slug:dataset_id>/", views.dataset_detail, name="dataset_detail"),
    path("data/download/<slug:name>.csv", views.data_download, name="data_download"),
    path("causal/", views.causal, name="causal"),
    path("simulate/", views.simulate, name="simulate"),
    path("simulate/compare/", views.simulate_compare, name="simulate_compare"),
    path("runs/<uuid:public_id>/", views.run_detail, name="run_detail"),
    path("runs/<uuid:public_id>/status.json", views.run_status, name="run_status"),
    path("runs/<uuid:public_id>/retry/", views.run_retry, name="run_retry"),
    path("runs/<uuid:public_id>/export.<str:fmt>", views.run_export, name="run_export"),
    path("reports/", views.reports, name="reports"),
    path("reports/summary.pdf", views.summary_pdf, name="summary_pdf"),
    path("reports/document/<str:name>", views.report_document, name="report_document"),
    path("activity/", views.activity, name="activity"),
    path("status/", views.status_page, name="status"),
    path("healthz", views.healthz, name="healthz"),
]
