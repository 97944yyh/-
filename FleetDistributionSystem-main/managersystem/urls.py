from django.urls import path
from . import views

urlpatterns = [
    # 车辆管理
    path('vehicles/', views.vehicle_list, name='vehicle_list'),
    path('vehicles/create/', views.vehicle_create, name='vehicle_create'),
    
    # 司机管理
    path('drivers/', views.driver_list, name='driver_list'),
    path('drivers/create/', views.driver_create, name='driver_create'),
    
    # 运单管理
    path('orders/pending/', views.order_pending_list, name='order_pending'),
    path('orders/assign/', views.assign_order, name='assign_order'),
    
    # 异常管理
    path('exceptions/create/', views.exception_create, name='exception_create'),
    
    # 报表
    path('reports/fleet_monthly/', views.fleet_monthly_report, name='fleet_monthly_report'),
    path('reports/driver_performance/', views.driver_performance, name='driver_performance'),
]
