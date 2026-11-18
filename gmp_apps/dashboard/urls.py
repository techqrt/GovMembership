from django.urls import path

from gmp_apps.dashboard.controllers.dashboard import DashboardDashboardViewController as Dashboard

urlpatterns = [
    path('get/', Dashboard.get, name='get_dashboard_dashboard'),
]
