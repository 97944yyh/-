from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/dispatcher/", views.dispatcher_login, name="dispatcher_login"),
    path("login/driver/", views.driver_login, name="driver_login"),
    path("logout/", views.logout, name="logout"),
    path("driver/", views.driver_center, name="driver_center"),
    path("vehicles/", views.vehicle_page, name="vehicle_page"),
    path("drivers/", views.driver_page, name="driver_page"),
    path("orders/", views.order_page, name="order_page"),
    path("exceptions/", views.exception_page, name="exception_page"),
    path("reports/", views.report_page, name="report_page"),
]
