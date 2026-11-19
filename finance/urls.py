from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("tai-chinh/", views.finance_hub, name="hub"),
    path("tai-chinh/phieu/<int:pk>/", views.transaction_detail, name="transaction_detail"),
    path("tai-chinh/phieu/<int:pk>/chung-tu/", views.transaction_receipt, name="transaction_receipt"),
    path("tai-chinh/so-cai.csv", views.ledger_csv, name="ledger_csv"),
]
