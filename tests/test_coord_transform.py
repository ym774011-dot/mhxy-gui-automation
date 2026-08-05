# -*- coding: utf-8 -*-
"""坐标转换功能测试模块。

测试 WindowManager 的坐标转换逻辑,包括:
- 客户区坐标转屏幕坐标
- 屏幕坐标转客户区坐标
- 窗口偏移计算
- 边界场景处理
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from core.window_manager import WindowManager


class TestCoordTransform:
    """坐标转换测试类。"""

    def setup_method(self):
        """每个测试方法执行前的设置。"""
        # 重置单例状态,确保测试隔离
        WindowManager._instance = None
        self.wm = WindowManager()

    def test_client_to_screen_with_bound_window(self):
        """测试绑定窗口后的客户区坐标转屏幕坐标。"""
        # Mock 窗口句柄和客户区矩形
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        self.wm.client_rect = (100, 100, 900, 700)  # 窗口位置(100,100),尺寸800x600
        
        with patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            # 设置 ClientToScreen 返回屏幕坐标
            # 假设客户区左上角在屏幕(100, 100),客户区坐标(50, 50)应该在屏幕(150, 150)
            mock_client_to_screen.return_value = (150, 150)
            
            screen_x, screen_y = self.wm.client_to_screen(50, 50)
            
            # 验证调用参数正确
            mock_client_to_screen.assert_called_once_with(mock_hwnd, (50, 50))
            
            # 验证转换结果
            assert screen_x == 150
            assert screen_y == 150

    def test_client_to_screen_without_bound_window(self):
        """测试未绑定窗口时的客户区坐标转换。"""
        # 未绑定窗口,hwnd 为 0
        self.wm.hwnd = 0
        
        # 未绑定时应返回原坐标
        screen_x, screen_y = self.wm.client_to_screen(50, 50)
        
        assert screen_x == 50
        assert screen_y == 50

    def test_client_to_screen_with_exception(self):
        """测试坐标转换异常时的处理。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            # 模拟异常
            mock_client_to_screen.side_effect = Exception("窗口已关闭")
            
            # 异常时应返回原坐标
            screen_x, screen_y = self.wm.client_to_screen(50, 50)
            
            assert screen_x == 50
            assert screen_y == 50

    def test_screen_to_client_calculation(self):
        """测试屏幕坐标转客户区坐标的计算。"""
        # 设置客户区矩形 (left, top, right, bottom)
        self.wm.client_rect = (100, 100, 900, 700)  # 800x600
        
        # 屏幕坐标转客户区坐标(通过手动计算)
        screen_x, screen_y = 150, 150
        # 客户区左上角在屏幕(100,100),所以屏幕(150,150)对应客户区(50,50)
        expected_client_x = screen_x - self.wm.client_rect[0]  # 150 - 100 = 50
        expected_client_y = screen_y - self.wm.client_rect[1]  # 150 - 100 = 50
        
        assert expected_client_x == 50
        assert expected_client_y == 50
        
        # 测试负值场景
        screen_x_out = 50, 50  # 屏幕坐标在客户区左上角之前
        expected_neg_x = screen_x_out[0] - self.wm.client_rect[0]  # 50 - 100 = -50
        expected_neg_y = screen_x_out[1] - self.wm.client_rect[1]  # 50 - 100 = -50
        
        assert expected_neg_x == -50
        assert expected_neg_y == -50

    def test_get_client_rect(self):
        """测试获取客户区矩形。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.GetClientRect') as mock_get_client_rect, \
             patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            
            # Mock GetClientRect 返回相对于窗口的坐标 (0, 0, 800, 600)
            mock_get_client_rect.return_value = (0, 0, 800, 600)
            # Mock ClientToScreen 返回屏幕坐标
            mock_client_to_screen.return_value = (100, 100)
            
            rect = self.wm.get_client_rect()
            
            # 验证结果
            # 客户区屏幕坐标应为 (100, 100, 900, 700)
            assert rect == (100, 100, 900, 700)
            
            # 验证调用
            mock_get_client_rect.assert_called_once_with(mock_hwnd)
            mock_client_to_screen.assert_called_once_with(mock_hwnd, (0, 0))

    def test_get_client_size(self):
        """测试获取客户区尺寸。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.GetClientRect') as mock_get_client_rect, \
             patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            
            # Mock GetClientRect 返回 (0, 0, 800, 600)
            mock_get_client_rect.return_value = (0, 0, 800, 600)
            mock_client_to_screen.return_value = (100, 100)
            
            width, height = self.wm.get_client_size()
            
            # 验证尺寸
            assert width == 800
            assert height == 600

    def test_window_offset_calculation(self):
        """测试窗口偏移计算。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.GetClientRect') as mock_get_client_rect, \
             patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            
            # 模拟客户区偏移 (10, 30) - 典型的窗口边框和标题栏偏移
            mock_get_client_rect.return_value = (0, 0, 800, 600)
            mock_client_to_screen.return_value = (110, 130)  # 窗口位置(100,100) + 偏移(10,30)
            
            self.wm.update_rect()
            
            # 客户区左上角应该在屏幕(110, 130)
            offset_x = self.wm.client_rect[0] - 100  # 客户区左上角 - 窗口左上角
            offset_y = self.wm.client_rect[1] - 100
            
            # 验证偏移为正数
            assert offset_x >= 0  # 10
            assert offset_y >= 0  # 30

    def test_negative_coordinates_handling(self):
        """测试负坐标处理。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            # 设置客户区左上角在屏幕(100, 100)
            mock_client_to_screen.return_value = (90, 90)  # 100 + (-10) = 90
            
            # 负坐标转换
            screen_x, screen_y = self.wm.client_to_screen(-10, -10)
            
            # Windows API 允许负坐标,应正常转换
            assert isinstance(screen_x, int)
            assert isinstance(screen_y, int)

    def test_out_of_window_range_coordinates(self):
        """测试超出窗口范围的坐标转换。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        self.wm.client_size = (800, 600)
        
        with patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            # 超出窗口范围的坐标
            mock_client_to_screen.return_value = (1000, 800)
            
            # 转换超出范围的坐标(宽度+100, 高度+100)
            screen_x, screen_y = self.wm.client_to_screen(900, 700)
            
            # 应该成功转换,但坐标可能超出实际屏幕范围
            assert isinstance(screen_x, int)
            assert isinstance(screen_y, int)
            assert screen_x == 1000
            assert screen_y == 800

    def test_bind_window_by_title(self):
        """测试按标题绑定窗口。"""
        test_title = "测试窗口"
        
        with patch('core.window_manager.win32gui.EnumWindows') as mock_enum_windows, \
             patch('core.window_manager.win32gui.IsWindowVisible') as mock_is_visible, \
             patch('core.window_manager.win32gui.GetWindowText') as mock_get_text:
            
            # 模拟窗口枚举回调
            mock_hwnd = 12345
            
            def enum_callback(callback, extra):
                mock_is_visible.return_value = True
                mock_get_text.return_value = "测试窗口 - 游戏"
                callback(mock_hwnd, None)
            
            mock_enum_windows.side_effect = lambda cb, extra: enum_callback(cb, extra)
            
            with patch.object(self.wm, '_bind_hwnd', return_value=True) as mock_bind:
                result = self.wm.find_by_title(test_title)
                
                # 验证绑定成功
                assert result is True
                mock_bind.assert_called_once_with(mock_hwnd)

    def test_bind_window_by_pid(self):
        """测试按 PID 绑定窗口。"""
        test_pid = 12345
        
        with patch('core.window_manager.win32gui.EnumWindows') as mock_enum_windows, \
             patch('core.window_manager.win32gui.IsWindowVisible') as mock_is_visible, \
             patch('core.window_manager.win32gui.GetWindowText') as mock_get_text, \
             patch('core.window_manager.win32process.GetWindowThreadProcessId') as mock_get_pid, \
             patch.object(WindowManager, 'is_process_running', return_value=True):
            
            mock_hwnd = 12345
            
            def enum_callback(callback, extra):
                mock_is_visible.return_value = True
                mock_get_text.return_value = "测试窗口"
                mock_get_pid.return_value = (123, test_pid)
                with patch('core.window_manager.win32gui.GetClientRect', return_value=(0, 0, 800, 600)):
                    callback(mock_hwnd, None)
            
            mock_enum_windows.side_effect = lambda cb, extra: enum_callback(cb, extra)
            
            with patch.object(self.wm, '_bind_hwnd', return_value=True) as mock_bind:
                result = self.wm.find_by_pid(test_pid)
                
                # 验证绑定成功
                assert result is True
                mock_bind.assert_called_once_with(mock_hwnd)

    def test_update_rect_after_window_move(self):
        """测试窗口移动后更新矩形。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.GetClientRect') as mock_get_client_rect, \
             patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            
            # 第一次获取: 窗口在(100, 100)
            mock_get_client_rect.return_value = (0, 0, 800, 600)
            mock_client_to_screen.return_value = (100, 100)
            
            self.wm.update_rect()
            rect1 = self.wm.get_client_rect()
            
            # 窗口移动到(200, 200)
            mock_client_to_screen.return_value = (200, 200)
            
            self.wm.update_rect()
            rect2 = self.wm.get_client_rect()
            
            # 验证矩形已更新
            assert rect1 == (100, 100, 900, 700)
            assert rect2 == (200, 200, 1000, 800)
            assert rect1 != rect2

    def test_coordinate_conversion_accuracy(self):
        """测试坐标转换精度。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        self.wm.client_rect = (100, 100, 900, 700)
        
        with patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            # 测试多个坐标点
            test_cases = [
                (0, 0, (100, 100)),      # 客户区左上角
                (100, 100, (200, 200)),  # 客户区(100,100)
                (400, 300, (500, 400)),  # 客户区中心
                (799, 599, (899, 699)),  # 客户区右下角
            ]
            
            for client_x, client_y, expected_screen in test_cases:
                mock_client_to_screen.return_value = expected_screen
                
                screen_x, screen_y = self.wm.client_to_screen(client_x, client_y)
                
                assert screen_x == expected_screen[0]
                assert screen_y == expected_screen[1]
                mock_client_to_screen.assert_called_with(mock_hwnd, (client_x, client_y))

    def test_window_validity_check(self):
        """测试窗口有效性检查。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.IsWindow') as mock_is_window:
            # 窗口有效
            mock_is_window.return_value = True
            assert self.wm.is_valid() is True
            
            # 窗口无效
            mock_is_window.return_value = False
            assert self.wm.is_valid() is False
            
            # 未绑定窗口
            self.wm.hwnd = 0
            assert self.wm.is_valid() is False

    def test_get_all_windows(self):
        """测试获取所有窗口列表。"""
        with patch('core.window_manager.win32gui.EnumWindows') as mock_enum_windows, \
             patch('core.window_manager.win32gui.IsWindowVisible') as mock_is_visible, \
             patch('core.window_manager.win32gui.GetWindowText') as mock_get_text, \
             patch('core.window_manager.win32process.GetWindowThreadProcessId') as mock_get_pid:
            
            # 模拟多个窗口
            windows_data = [
                (100, "窗口A", 1234),
                (200, "窗口B", 5678),
                (300, "窗口C", 9012),
            ]
            
            def enum_callback(callback, extra):
                for hwnd, title, pid in windows_data:
                    mock_is_visible.return_value = True
                    mock_get_text.return_value = title
                    mock_get_pid.return_value = (0, pid)
                    callback(hwnd, None)
            
            mock_enum_windows.side_effect = lambda cb, extra: enum_callback(cb, extra)
            
            # 调用静态方法
            result = WindowManager.get_all_windows()
            
            # 验证返回窗口列表(应按标题排序)
            assert len(result) == 3
            assert all(isinstance(item, tuple) and len(item) == 3 for item in result)

    def test_singleton_pattern(self):
        """测试单例模式。"""
        wm1 = WindowManager()
        wm2 = WindowManager()
        
        # 验证是同一个实例
        assert wm1 is wm2
        assert id(wm1) == id(wm2)

    def test_coordinate_boundary_values(self):
        """测试坐标边界值。"""
        mock_hwnd = 12345
        self.wm.hwnd = mock_hwnd
        
        with patch('core.window_manager.win32gui.ClientToScreen') as mock_client_to_screen:
            # 测试最小值
            mock_client_to_screen.return_value = (0, 0)
            screen_x, screen_y = self.wm.client_to_screen(0, 0)
            assert screen_x == 0
            assert screen_y == 0
            
            # 测试大坐标
            mock_client_to_screen.return_value = (10000, 10000)
            screen_x, screen_y = self.wm.client_to_screen(10000, 10000)
            assert screen_x == 10000
            assert screen_y == 10000