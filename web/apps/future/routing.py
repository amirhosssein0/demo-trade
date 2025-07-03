from django.urls import re_path
from .consumers import FuturesChartSocket

websocket_urlpatterns = [
    re_path(r'ws/future/chart/$', FuturesChartSocket.as_asgi()),
] 