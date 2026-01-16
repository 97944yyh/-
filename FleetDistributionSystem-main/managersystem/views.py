from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db import connection, transaction, IntegrityError
from django.db.models import Count
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json
from .models import Vehicle, Driver, Order, ExceptionRecord, Fleet, Dispatcher, DistributionCenter

VEHICLE_STATUS_LABELS = {
    "Idle": "空闲",
    "Loading": "装货中",
    "Busy": "运输中",
    "Maintenance": "维修中",
    "Exception": "异常",
}

ORDER_STATUS_LABELS = {
    "Pending": "待分配",
    "Loading": "装货中",
    "In-Transit": "运输中",
    "Delivered": "已完成",
}

EXCEPTION_TYPE_LABELS = {
    "Transit_Exception": "运输中异常",
    "Idle_Exception": "空闲异常",
}

HANDLE_STATUS_LABELS = {
    "Unprocessed": "未处理",
    "Processed": "已处理",
}

ROLE_LABELS = {
    "dispatcher": "部门主管",
    "driver": "司机",
}

# 辅助函数：统一返回JSON格式
def success_response(data=None, message="Success"):
    return JsonResponse({'code': 200, 'message': message, 'data': data})

def error_response(message="Error", code=400):
    return JsonResponse({'code': code, 'message': message})

# =============================================
# Auth helpers
# =============================================

def _ensure_dispatcher(request):
    role = request.session.get("role")
    if role == "dispatcher":
        return None
    if role == "driver":
        messages.error(request, "当前为司机身份，无法访问该页面。")
        return redirect("driver_center")
    messages.info(request, "请先以部门主管身份登录。")
    return redirect("dispatcher_login")


def _ensure_driver(request):
    role = request.session.get("role")
    if role == "driver":
        return None
    if role == "dispatcher":
        messages.error(request, "当前为部门主管身份，无法访问司机页面。")
        return redirect("dashboard")
    messages.info(request, "请先以司机身份登录。")
    return redirect("driver_login")


# =============================================
# Auth pages
# =============================================

def dispatcher_login(request):
    if request.method == "POST":
        dispatcher_id = request.POST.get("dispatcher_id", "").strip()
        password = request.POST.get("password", "").strip()
        if not dispatcher_id or not password:
            messages.error(request, "请填写账号和密码。")
            return redirect("dispatcher_login")

        dispatcher = Dispatcher.objects.filter(
            dispatcher_id=dispatcher_id,
            password=password,
        ).select_related("fleet").first()
        if not dispatcher:
            messages.error(request, "账号或密码错误。")
            return redirect("dispatcher_login")

        request.session["role"] = "dispatcher"
        request.session["user_id"] = dispatcher.dispatcher_id
        request.session["user_name"] = dispatcher.name
        request.session["fleet_id"] = dispatcher.fleet_id
        messages.success(request, "登录成功。")
        return redirect("dashboard")

    return render(request, "managersystem/login_dispatcher.html")


def driver_login(request):
    if request.method == "POST":
        driver_id = request.POST.get("driver_id", "").strip()
        phone = request.POST.get("phone", "").strip()
        if not driver_id or not phone:
            messages.error(request, "请填写工号和手机号。")
            return redirect("driver_login")

        driver = Driver.objects.filter(driver_id=driver_id, phone=phone).select_related("fleet").first()
        if not driver:
            messages.error(request, "工号或手机号不正确。")
            return redirect("driver_login")

        request.session["role"] = "driver"
        request.session["user_id"] = driver.driver_id
        request.session["user_name"] = driver.name
        request.session["fleet_id"] = driver.fleet_id
        messages.success(request, "登录成功。")
        return redirect("driver_center")

    return render(request, "managersystem/login_driver.html")


def logout(request):
    request.session.flush()
    messages.success(request, "已退出登录。")
    return redirect("dispatcher_login")

# =============================================
# Frontend pages
# =============================================

def landing_page(request):
    if request.session.get("role"):
        return redirect("dashboard")

    stats = {}
    stats_error = None
    try:
        stats = {
            "centers": DistributionCenter.objects.count(),
            "fleets": Fleet.objects.count(),
            "vehicles": Vehicle.objects.count(),
            "drivers": Driver.objects.count(),
            "orders": Order.objects.count(),
            "exceptions": ExceptionRecord.objects.count(),
            "active_orders": Order.objects.filter(status__in=["Pending", "Loading", "In-Transit"]).count(),
        }
    except Exception as exc:
        stats_error = f"统计信息加载失败：{exc}"

    return render(
        request,
        "managersystem/landing.html",
        {
            "stats": stats,
            "stats_error": stats_error,
        },
    )

def dashboard(request):
    redirect_response = _ensure_dispatcher(request)
    if redirect_response:
        return redirect_response

    dispatcher_fleet_id = request.session.get("fleet_id")
    vehicle_queryset = Vehicle.objects.all()
    driver_queryset = Driver.objects.all()
    exception_queryset = ExceptionRecord.objects.all()

    if dispatcher_fleet_id:
        vehicle_queryset = vehicle_queryset.filter(fleet_id=dispatcher_fleet_id)
        driver_queryset = driver_queryset.filter(fleet_id=dispatcher_fleet_id)
        exception_queryset = exception_queryset.filter(vehicle_plate__fleet_id=dispatcher_fleet_id)

    status_summary = {key: 0 for key in VEHICLE_STATUS_LABELS}
    for row in vehicle_queryset.values("status").annotate(total=Count("status")):
        status_summary[row["status"]] = row["total"]

    stats = {
        "total_vehicles": sum(status_summary.values()),
        "total_drivers": driver_queryset.count(),
        "pending_orders": Order.objects.filter(status="Pending").count(),
        "unprocessed_exceptions": exception_queryset.filter(handle_status="Unprocessed").count(),
    }

    weekly_alerts = []
    weekly_alert_error = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT plate_number, fleet_name, driver_name, exception_type, occur_time FROM VW_Weekly_Alert"
            )
            columns = [col[0] for col in cursor.description]
            weekly_alerts = [dict(zip(columns, row)) for row in cursor.fetchall()]
            for row in weekly_alerts:
                row["exception_type_label"] = EXCEPTION_TYPE_LABELS.get(
                    row.get("exception_type"), row.get("exception_type")
                )
        if dispatcher_fleet_id:
            fleet_name = Fleet.objects.filter(fleet_id=dispatcher_fleet_id).values_list("fleet_name", flat=True).first()
            if fleet_name:
                weekly_alerts = [row for row in weekly_alerts if row.get("fleet_name") == fleet_name]
    except Exception as exc:
        weekly_alert_error = f"读取视图失败：{exc}"

    status_summary_rows = [
        {"code": code, "label": label, "total": status_summary.get(code, 0)}
        for code, label in VEHICLE_STATUS_LABELS.items()
    ]

    return render(
        request,
        "managersystem/dashboard.html",
        {
            "status_summary": status_summary_rows,
            "stats": stats,
            "weekly_alerts": weekly_alerts,
            "weekly_alert_error": weekly_alert_error,
        },
    )


def vehicle_page(request):
    redirect_response = _ensure_dispatcher(request)
    if redirect_response:
        return redirect_response

    dispatcher_fleet_id = request.session.get("fleet_id")
    if request.method == "POST":
        plate_number = request.POST.get("plate_number", "").strip()
        fleet_id = request.POST.get("fleet_id", "").strip()
        max_weight = request.POST.get("max_weight", "").strip()
        max_volume = request.POST.get("max_volume", "").strip()
        status = request.POST.get("status", "Idle")

        if not plate_number or not fleet_id or not max_weight or not max_volume:
            messages.error(request, "请填写完整的车辆信息。")
            return redirect("vehicle_page")

        if dispatcher_fleet_id and str(fleet_id) != str(dispatcher_fleet_id):
            messages.error(request, "只能操作自己车队的车辆。")
            return redirect("vehicle_page")

        try:
            Vehicle.objects.create(
                plate_number=plate_number,
                fleet_id=fleet_id,
                max_weight=max_weight,
                max_volume=max_volume,
                status=status or "Idle",
            )
            messages.success(request, "车辆创建成功。")
        except Exception as exc:
            messages.error(request, f"车辆创建失败：{exc}")
        return redirect("vehicle_page")

    fleet_filter = request.GET.get("fleet_id")
    status_filter = request.GET.get("status")

    vehicles = Vehicle.objects.select_related("fleet").all()
    fleets = Fleet.objects.all()
    if dispatcher_fleet_id:
        vehicles = vehicles.filter(fleet_id=dispatcher_fleet_id)
        fleets = fleets.filter(fleet_id=dispatcher_fleet_id)
    if fleet_filter:
        vehicles = vehicles.filter(fleet_id=fleet_filter)
    if status_filter:
        vehicles = vehicles.filter(status=status_filter)
    for vehicle in vehicles:
        vehicle.status_label = VEHICLE_STATUS_LABELS.get(vehicle.status, vehicle.status)

    return render(
        request,
        "managersystem/vehicles.html",
        {
            "vehicles": vehicles,
            "fleets": fleets,
            "status_choices": list(VEHICLE_STATUS_LABELS.items()),
            "fleet_filter": fleet_filter or "",
            "status_filter": status_filter or "",
        },
    )


def driver_page(request):
    redirect_response = _ensure_dispatcher(request)
    if redirect_response:
        return redirect_response

    dispatcher_fleet_id = request.session.get("fleet_id")
    if request.method == "POST":
        driver_id = request.POST.get("driver_id", "").strip()
        name = request.POST.get("name", "").strip()
        license_level = request.POST.get("license_level", "").strip()
        phone = request.POST.get("phone", "").strip()
        fleet_id = request.POST.get("fleet_id", "").strip()

        if not driver_id or not name or not license_level or not fleet_id:
            messages.error(request, "请填写完整的司机信息。")
            return redirect("driver_page")

        if dispatcher_fleet_id and str(fleet_id) != str(dispatcher_fleet_id):
            messages.error(request, "只能操作自己车队的司机。")
            return redirect("driver_page")

        try:
            Driver.objects.create(
                driver_id=driver_id,
                name=name,
                license_level=license_level,
                phone=phone or None,
                fleet_id=fleet_id,
            )
            messages.success(request, "司机创建成功。")
        except Exception as exc:
            messages.error(request, f"司机创建失败：{exc}")
        return redirect("driver_page")

    fleet_filter = request.GET.get("fleet_id")
    drivers = Driver.objects.select_related("fleet").all()
    fleets = Fleet.objects.all()
    if dispatcher_fleet_id:
        drivers = drivers.filter(fleet_id=dispatcher_fleet_id)
        fleets = fleets.filter(fleet_id=dispatcher_fleet_id)
    if fleet_filter:
        drivers = drivers.filter(fleet_id=fleet_filter)

    return render(
        request,
        "managersystem/drivers.html",
        {
            "drivers": drivers,
            "fleets": fleets,
            "fleet_filter": fleet_filter or "",
        },
    )


def order_page(request):
    redirect_response = _ensure_dispatcher(request)
    if redirect_response:
        return redirect_response

    dispatcher_fleet_id = request.session.get("fleet_id")
    if request.method == "POST":
        order_id = request.POST.get("order_id", "").strip()
        vehicle_plate = request.POST.get("vehicle_plate", "").strip()
        driver_id = request.POST.get("driver_id", "").strip()

        if not order_id or not vehicle_plate or not driver_id:
            messages.error(request, "请填写完整的分配信息。")
            return redirect("order_page")

        try:
            vehicle = Vehicle.objects.get(plate_number=vehicle_plate)
            driver = Driver.objects.get(driver_id=driver_id)
            if dispatcher_fleet_id:
                if str(vehicle.fleet_id) != str(dispatcher_fleet_id) or str(driver.fleet_id) != str(dispatcher_fleet_id):
                    messages.error(request, "只能为自己车队分配运单。")
                    return redirect("order_page")

            with transaction.atomic():
                order = Order.objects.get(order_id=order_id)
                order.vehicle_plate_id = vehicle_plate
                order.driver_id = driver_id
                order.status = "Loading"
                order.start_time = timezone.now()
                order.save()
            messages.success(request, "运单分配成功。")
        except (Vehicle.DoesNotExist, Driver.DoesNotExist):
            messages.error(request, "车辆或司机不存在。")
        except IntegrityError as exc:
            messages.error(request, f"分配失败：{exc}")
        except Order.DoesNotExist:
            messages.error(request, "运单不存在。")
        except Exception as exc:
            messages.error(request, f"分配失败：{exc}")
        return redirect("order_page")

    pending_orders = Order.objects.filter(status="Pending").order_by("order_id")
    recent_orders = Order.objects.select_related("vehicle_plate", "driver").order_by("-start_time", "-order_id")
    for order in pending_orders:
        order.status_label = ORDER_STATUS_LABELS.get(order.status, order.status)
    for order in recent_orders:
        order.status_label = ORDER_STATUS_LABELS.get(order.status, order.status)

    vehicles = Vehicle.objects.order_by("plate_number")
    drivers = Driver.objects.order_by("driver_id")
    if dispatcher_fleet_id:
        recent_orders = recent_orders.filter(vehicle_plate__fleet_id=dispatcher_fleet_id)
        vehicles = vehicles.filter(fleet_id=dispatcher_fleet_id)
        drivers = drivers.filter(fleet_id=dispatcher_fleet_id)

    recent_orders = recent_orders[:50]
    for vehicle in vehicles:
        vehicle.status_label = VEHICLE_STATUS_LABELS.get(vehicle.status, vehicle.status)

    return render(
        request,
        "managersystem/orders.html",
        {
            "pending_orders": pending_orders,
            "recent_orders": recent_orders,
            "vehicles": vehicles,
            "drivers": drivers,
        },
    )


def exception_page(request):
    redirect_response = _ensure_dispatcher(request)
    if redirect_response:
        return redirect_response

    dispatcher_fleet_id = request.session.get("fleet_id")
    if request.method == "POST":
        vehicle_plate = request.POST.get("vehicle_plate", "").strip()
        driver_id = request.POST.get("driver_id", "").strip()
        exception_type = request.POST.get("exception_type", "").strip()
        specific_event = request.POST.get("specific_event", "").strip()
        fine_amount = request.POST.get("fine_amount", "").strip()
        description = request.POST.get("description", "").strip()

        if not vehicle_plate or not driver_id or not exception_type:
            messages.error(request, "请填写完整的异常信息。")
            return redirect("exception_page")

        try:
            vehicle = Vehicle.objects.get(plate_number=vehicle_plate)
            driver = Driver.objects.get(driver_id=driver_id)
            if dispatcher_fleet_id:
                if str(vehicle.fleet_id) != str(dispatcher_fleet_id) or str(driver.fleet_id) != str(dispatcher_fleet_id):
                    messages.error(request, "只能录入自己车队的异常。")
                    return redirect("exception_page")

            ExceptionRecord.objects.create(
                vehicle_plate_id=vehicle_plate,
                driver_id=driver_id,
                exception_type=exception_type,
                specific_event=specific_event or None,
                fine_amount=fine_amount or 0,
                description=description or None,
                handle_status="Unprocessed",
            )
            messages.success(request, "异常记录成功。")
        except Exception as exc:
            messages.error(request, f"异常记录失败：{exc}")
        return redirect("exception_page")

    exceptions = ExceptionRecord.objects.select_related("vehicle_plate", "driver").order_by("-occur_time")
    vehicles = Vehicle.objects.order_by("plate_number")
    drivers = Driver.objects.order_by("driver_id")
    if dispatcher_fleet_id:
        exceptions = exceptions.filter(vehicle_plate__fleet_id=dispatcher_fleet_id)
        vehicles = vehicles.filter(fleet_id=dispatcher_fleet_id)
        drivers = drivers.filter(fleet_id=dispatcher_fleet_id)
    exceptions = exceptions[:50]
    for record in exceptions:
        record.exception_type_label = EXCEPTION_TYPE_LABELS.get(
            record.exception_type, record.exception_type
        )
        record.handle_status_label = HANDLE_STATUS_LABELS.get(
            record.handle_status, record.handle_status
        )

    return render(
        request,
        "managersystem/exceptions.html",
        {
            "exceptions": exceptions,
            "vehicles": vehicles,
            "drivers": drivers,
            "exception_types": list(EXCEPTION_TYPE_LABELS.items()),
        },
    )


def report_page(request):
    redirect_response = _ensure_dispatcher(request)
    if redirect_response:
        return redirect_response

    dispatcher_fleet_id = request.session.get("fleet_id")
    fleets = Fleet.objects.order_by("fleet_id")
    drivers = Driver.objects.order_by("driver_id")
    if dispatcher_fleet_id:
        fleets = fleets.filter(fleet_id=dispatcher_fleet_id)
        drivers = drivers.filter(fleet_id=dispatcher_fleet_id)

    fleet_report = None
    fleet_error = None
    driver_report = None
    driver_exceptions = None
    driver_error = None

    fleet_id = request.GET.get("fleet_id", "").strip()
    report_date = request.GET.get("report_date", "").strip()
    if fleet_id and report_date:
        if dispatcher_fleet_id and str(fleet_id) != str(dispatcher_fleet_id):
            fleet_error = "只能查询自己车队的报表。"
        else:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("EXEC SP_Calc_Fleet_Monthly_Report %s, %s", [fleet_id, report_date])
                    columns = [col[0] for col in cursor.description]
                    fleet_report = [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as exc:
                fleet_error = f"报表查询失败：{exc}"

    driver_id = request.GET.get("driver_id", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    if driver_id and start_date and end_date:
        allowed_driver_ids = [str(d.driver_id) for d in drivers]
        if dispatcher_fleet_id and str(driver_id) not in allowed_driver_ids:
            driver_error = "只能查询自己车队的司机绩效。"
        else:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("EXEC SP_Get_Driver_Performance %s, %s, %s", [driver_id, start_date, end_date])
                    summary_rows = cursor.fetchall()
                    summary_columns = [col[0] for col in cursor.description]
                    driver_report = [dict(zip(summary_columns, row)) for row in summary_rows]

                    driver_exceptions = []
                    if cursor.nextset():
                        detail_rows = cursor.fetchall()
                        if cursor.description:
                            detail_columns = [col[0] for col in cursor.description]
                            driver_exceptions = [dict(zip(detail_columns, row)) for row in detail_rows]
            except Exception as exc:
                driver_error = f"报表查询失败：{exc}"

    return render(
        request,
        "managersystem/reports.html",
        {
            "fleets": fleets,
            "drivers": drivers,
            "fleet_id": fleet_id,
            "report_date": report_date,
            "fleet_report": fleet_report,
            "fleet_error": fleet_error,
            "driver_id": driver_id,
            "start_date": start_date,
            "end_date": end_date,
            "driver_report": driver_report,
            "driver_exceptions": driver_exceptions,
            "driver_error": driver_error,
        },
    )

# =============================================
# 1. 车辆管理接口
# =============================================

def driver_center(request):
    redirect_response = _ensure_driver(request)
    if redirect_response:
        return redirect_response

    driver_id = request.session.get("user_id")
    driver = Driver.objects.select_related("fleet").filter(driver_id=driver_id).first()
    if not driver:
        messages.error(request, "未找到司机信息，请重新登录。")
        return redirect("driver_login")

    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    performance_summary = None
    performance_exceptions = None
    performance_error = None

    if start_date and end_date:
        try:
            with connection.cursor() as cursor:
                cursor.execute("EXEC SP_Get_Driver_Performance %s, %s, %s", [driver_id, start_date, end_date])
                summary_rows = cursor.fetchall()
                summary_columns = [col[0] for col in cursor.description]
                performance_summary = [dict(zip(summary_columns, row)) for row in summary_rows]

                performance_exceptions = []
                if cursor.nextset():
                    detail_rows = cursor.fetchall()
                    if cursor.description:
                        detail_columns = [col[0] for col in cursor.description]
                        performance_exceptions = [dict(zip(detail_columns, row)) for row in detail_rows]
        except Exception as exc:
            performance_error = f"查询失败：{exc}"

    orders = (
        Order.objects.select_related("vehicle_plate")
        .filter(driver_id=driver_id)
        .order_by("-start_time", "-order_id")[:50]
    )
    for order in orders:
        order.status_label = ORDER_STATUS_LABELS.get(order.status, order.status)

    exceptions = (
        ExceptionRecord.objects.select_related("vehicle_plate")
        .filter(driver_id=driver_id)
        .order_by("-occur_time")[:50]
    )
    for record in exceptions:
        record.exception_type_label = EXCEPTION_TYPE_LABELS.get(
            record.exception_type, record.exception_type
        )
        record.handle_status_label = HANDLE_STATUS_LABELS.get(
            record.handle_status, record.handle_status
        )

    return render(
        request,
        "managersystem/driver_center.html",
        {
            "driver": driver,
            "orders": orders,
            "exceptions": exceptions,
            "start_date": start_date,
            "end_date": end_date,
            "performance_summary": performance_summary,
            "performance_exceptions": performance_exceptions,
            "performance_error": performance_error,
        },
    )


def vehicle_list(request):
    """获取车辆列表，支持按车队ID筛选"""
    fleet_id = request.GET.get('fleet_id')
    status = request.GET.get('status')
    
    queryset = Vehicle.objects.all()
    if fleet_id:
        queryset = queryset.filter(fleet_id=fleet_id)
    if status:
        queryset = queryset.filter(status=status)
        
    data = []
    for v in queryset:
        data.append({
            'plate_number': v.plate_number,
            'status': v.status,
            'max_weight': v.max_weight,
            'max_volume': v.max_volume,
            'fleet_name': v.fleet.fleet_name
        })
    return success_response(data)

@csrf_exempt
def vehicle_create(request):
    """录入车辆信息"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            Vehicle.objects.create(
                plate_number=data['plate_number'],
                fleet_id=data['fleet_id'],
                max_weight=data['max_weight'],
                max_volume=data['max_volume'],
                status=data.get('status', 'Idle')
            )
            return success_response(message="Vehicle created successfully")
        except Exception as e:
            return error_response(str(e))
    return error_response("Method not allowed", 405)

# =============================================
# 2. 司机管理接口
# =============================================

def driver_list(request):
    """获取司机列表"""
    fleet_id = request.GET.get('fleet_id')
    queryset = Driver.objects.all()
    if fleet_id:
        queryset = queryset.filter(fleet_id=fleet_id)
        
    data = []
    for d in queryset:
        data.append({
            'driver_id': d.driver_id,
            'name': d.name,
            'license_level': d.license_level,
            'phone': d.phone,
            'fleet_name': d.fleet.fleet_name
        })
    return success_response(data)

@csrf_exempt
def driver_create(request):
    """录入司机信息"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            Driver.objects.create(
                driver_id=data['driver_id'],
                name=data['name'],
                license_level=data['license_level'],
                phone=data.get('phone'),
                fleet_id=data['fleet_id']
            )
            return success_response(message="Driver created successfully")
        except Exception as e:
            return error_response(str(e))
    return error_response("Method not allowed", 405)

# =============================================
# 3. 核心业务：运单分配
# =============================================

def order_pending_list(request):
    """获取待处理运单"""
    orders = Order.objects.filter(status='Pending')
    data = [{'order_id': o.order_id, 'destination': o.destination, 'weight': o.cargo_weight} for o in orders]
    return success_response(data)

@csrf_exempt
def assign_order(request):
    """将运单分配给车辆"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data['order_id']
            vehicle_plate = data['vehicle_plate']
            driver_id = data['driver_id']
            
            # 使用原生 SQL 捕获触发器错误，或者依赖 Django 捕获 DB 异常
            # 因为我们在数据库层面设置了 TRG_Load_Check 触发器，如果超载会抛错
            with transaction.atomic():
                order = Order.objects.get(order_id=order_id)
                order.vehicle_plate_id = vehicle_plate
                order.driver_id = driver_id
                order.status = 'Loading' # 状态流转
                order.start_time = timezone.now()
                order.save()
                
            return success_response(message="Order assigned successfully")
            
        except IntegrityError as e:
            # 捕获数据库触发器抛出的错误 (SQL Server通常会通过 IntegrityError 或 DataError 传递回来)
            return error_response(f"Assignment failed: Database Constraint/Trigger Error - {str(e)}")
        except Order.DoesNotExist:
            return error_response("Order not found")
        except Exception as e:
            return error_response(str(e))
    return error_response("Method not allowed", 405)

# =============================================
# 4. 异常管理
# =============================================

@csrf_exempt
def exception_create(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            ExceptionRecord.objects.create(
                vehicle_plate_id=data['vehicle_plate'],
                driver_id=data['driver_id'],
                exception_type=data['exception_type'],
                specific_event=data['specific_event'],
                description=data.get('description'),
                handle_status='Unprocessed'
            )
            # 数据库触发器 TRG_Exception_Flag 会自动将车辆状态改为 Exception
            return success_response(message="Exception recorded")
        except Exception as e:
            return error_response(str(e))
    return error_response("Method not allowed", 405)

# =============================================
# 5. 报表与存储过程调用
# =============================================

def fleet_monthly_report(request):
    """调用存储过程 SP_Calc_Fleet_Monthly_Report"""
    fleet_id = request.GET.get('fleet_id')
    report_date = request.GET.get('date') # Format: YYYY-MM-DD
    
    if not fleet_id or not report_date:
        return error_response("Missing parameters")

    with connection.cursor() as cursor:
        # 注意：不同数据库驱动调用存储过程语法不同
        # SQL Server: EXEC SP_Calc_Fleet_Monthly_Report %s, %s
        cursor.execute("EXEC SP_Calc_Fleet_Monthly_Report %s, %s", [fleet_id, report_date])
        result = cursor.fetchall() # 获取结果集
        
    # 格式化结果
    columns = [col[0] for col in cursor.description]
    data = [dict(zip(columns, row)) for row in result]
    
    return success_response(data)

def driver_performance(request):
    """调用存储过程 SP_Get_Driver_Performance"""
    driver_id = request.GET.get('driver_id')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not driver_id:
        return error_response("Missing driver_id")
        
    with connection.cursor() as cursor:
        cursor.execute("EXEC SP_Get_Driver_Performance %s, %s, %s", [driver_id, start_date, end_date])
        # 存储过程返回两个结果集，Django cursor 通常只能获取第一个
        # 如果需要获取多个，需要底层驱动支持 .nextset()
        
        # 获取第一个结果集 (Performance Summary)
        summary_result = cursor.fetchall()
        summary_cols = [col[0] for col in cursor.description]
        summary_data = [dict(zip(summary_cols, row)) for row in summary_result]
        
        exceptions_data = []
        if cursor.nextset(): # 尝试获取第二个结果集 (Exception details)
            details_result = cursor.fetchall()
            if cursor.description:
                details_cols = [col[0] for col in cursor.description]
                exceptions_data = [dict(zip(details_cols, row)) for row in details_result]
            
    return success_response({
        'summary': summary_data,
        'exceptions': exceptions_data
    })
