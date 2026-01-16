USE FleetDistributionDB;
GO

-- =============================================
-- 07. 模拟数据插入脚本
-- =============================================

-- 1. 插入配送中心
INSERT INTO Distribution_Center (center_name, address) VALUES 
('华东一号仓', '上海市浦东新区物流大道88号'),
('华北二号仓', '北京市大兴区魏善庄镇'),
('华南三号仓', '广州市白云区太和镇');
GO

-- 2. 插入车队
-- 假设 center_id 自增从 1 开始
INSERT INTO Fleet (fleet_name, center_id) VALUES 
('干线运输一队', 1), -- 属于华东
('城市配送A队', 1), -- 属于华东
('京津冀特快队', 2); -- 属于华北
GO

-- 3. 插入调度主管
-- 1:1 对应车队
INSERT INTO Dispatcher (dispatcher_id, name, password, fleet_id) VALUES 
('DP001', '张主管', '123456', 1),
('DP002', '李调度', 'password', 2),
('DP003', '王经理', 'admin888', 3);
GO

-- 4. 插入车辆
-- 干线一队 (fleet_id=1)
INSERT INTO Vehicle (plate_number, fleet_id, max_weight, max_volume, status) VALUES 
('沪A-88888', 1, 30.00, 100.00, 'Idle'),
('沪B-12345', 1, 20.00, 60.00, 'Busy'),
('沪A-99999', 1, 30.00, 100.00, 'Maintenance');

-- 城配A队 (fleet_id=2)
INSERT INTO Vehicle (plate_number, fleet_id, max_weight, max_volume, status) VALUES 
('沪C-56789', 2, 5.00, 15.00, 'Idle'),
('沪C-11111', 2, 5.00, 15.00, 'Exception');

-- 京津冀特快 (fleet_id=3)
INSERT INTO Vehicle (plate_number, fleet_id, max_weight, max_volume, status) VALUES 
('京K-66666', 3, 15.00, 45.00, 'Loading');
GO

-- 5. 插入司机
INSERT INTO Driver (driver_id, name, license_level, phone, fleet_id) VALUES 
-- 对应干线一队
('DR001', '赵师傅', 'A1', '13800138001', 1),
('DR002', '钱师傅', 'A2', '13800138002', 1),
('DR003', '孙师傅', 'A1', '13800138003', 1),
-- 对应城配A队
('DR004', '李小哥', 'B1', '13900139001', 2),
('DR005', '周小哥', 'C1', '13900139002', 2),
-- 对应京津冀
('DR006', '吴老六', 'A2', '13700137001', 3);
GO

-- 6. 插入运单
INSERT INTO [Order] (Order_id, cargo_weight, cargo_volume, destination, status, vehicle_plate, driver_id, start_time, end_time) VALUES 
-- 沪B-12345 正在运输中
('ORD-20231001-01', 15.00, 40.00, '杭州萧山', 'In-Transit', '沪B-12345', 'DR002', DATEADD(HOUR, -5, GETDATE()), NULL),
-- 京K-66666 正在装货
('ORD-20231002-02', 10.00, 30.00, '天津滨海', 'Loading', '京K-66666', 'DR006', GETDATE(), NULL),
-- 已完成的订单
('ORD-20230928-03', 25.00, 80.00, '南京江宁', 'Delivered', '沪A-88888', 'DR001', DATEADD(DAY, -5, GETDATE()), DATEADD(DAY, -4, GETDATE())),
-- 待处理订单
('ORD-20231003-04', 2.00, 5.00, '上海徐汇', 'Pending', NULL, NULL, NULL, NULL);
GO

-- 7. 插入异常记录
INSERT INTO Exception_Record (vehicle_plate, driver_id, occur_time, exception_type, specific_event, fine_amount, handle_status, description) VALUES 
-- 沪C-11111 发生了异常
('沪C-11111', 'DR005', DATEADD(HOUR, -2, GETDATE()), 'Idle_Exception', '车辆无法启动', 0.00, 'Unprocessed', '早晨启动时发现电瓶亏电'),
-- 历史处理过的异常
('沪B-12345', 'DR002', DATEADD(MONTH, -1, GETDATE()), 'Transit_Exception', '轻微碰擦', 500.00, 'Processed', '高速服务区倒车时碰擦');
GO
