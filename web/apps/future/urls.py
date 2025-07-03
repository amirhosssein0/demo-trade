from django.urls import path
from .views import futures_live_report, create_futures_order

urlpatterns = [
    path('futures-live-report/', futures_live_report, name='futures_live_report'),
    path('create/', create_futures_order, name='create_futures_order'),
]
