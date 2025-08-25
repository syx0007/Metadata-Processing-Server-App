import os
import sys
import threading
import webbrowser
from PySide6.QtWidgets import (QApplication, QMainWindow, QSystemTrayIcon, 
                              QMenu, QStyle, QMessageBox, QDialog, QVBoxLayout, 
                              QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                              QGroupBox, QCheckBox, QStatusBar, QTextEdit)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QAction
import requests
import json

# 添加资源管理函数
def resource_path(relative_path):
    """获取资源的绝对路径，支持开发环境和PyInstaller打包环境"""
    try:
        # PyInstaller创建临时文件夹，将路径存储在_MEIPASS中
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(400, 250)
        
        layout = QVBoxLayout()
        
        # 缓存目录设置
        cache_group = QGroupBox("缓存目录")
        cache_layout = QVBoxLayout()
        
        cache_label = QLabel("歌曲缓存目录:")
        cache_layout.addWidget(cache_label)
        
        cache_edit_layout = QHBoxLayout()
        self.cache_edit = QLineEdit()
        self.cache_edit.setPlaceholderText("请输入缓存目录路径")
        cache_edit_layout.addWidget(self.cache_edit)
        
        self.browse_btn = QPushButton("浏览...")
        cache_edit_layout.addWidget(self.browse_btn)
        cache_layout.addLayout(cache_edit_layout)
        
        cache_group.setLayout(cache_layout)
        layout.addWidget(cache_group)
        
        # 服务器设置
        server_group = QGroupBox("服务器设置")
        server_layout = QVBoxLayout()
        
        # 主机地址（只读）
        host_layout = QHBoxLayout()
        host_label = QLabel("主机地址:")
        self.host_edit = QLineEdit("127.0.0.1")
        self.host_edit.setReadOnly(True)  # 设置为只读
        self.host_edit.setStyleSheet("background-color: #f0f0f0;")  # 灰色背景表示不可编辑
        host_layout.addWidget(host_label)
        host_layout.addWidget(self.host_edit)
        server_layout.addLayout(host_layout)
        
        # 端口设置
        port_layout = QHBoxLayout()
        port_label = QLabel("端口号:")
        self.port_edit = QLineEdit("5000")
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_edit)
        server_layout.addLayout(port_layout)
        
        # 端口警告提示
        port_warning = QLabel("⚠️ 更改端口后，请确保作品中设置的端口号与此一致，否则无法使用！")
        port_warning.setWordWrap(True)
        port_warning.setStyleSheet("color: #ff6b6b; font-size: 10px;")
        server_layout.addWidget(port_warning)
        
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.cancel_btn = QPushButton("取消")
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 连接信号
        self.browse_btn.clicked.connect(self.browse_directory)
        self.save_btn.clicked.connect(self.on_save)
        self.cancel_btn.clicked.connect(self.reject)
        
        # 记录原始端口号
        self.original_port = ""
    
    def browse_directory(self):
        from PySide6.QtWidgets import QFileDialog
        directory = QFileDialog.getExistingDirectory(self, "选择缓存目录")
        if directory:
            self.cache_edit.setText(directory)
    
    def on_save(self):
        """保存前的端口号检查"""
        new_port = self.port_edit.text().strip()
        
        # 检查端口号是否有效
        try:
            port_num = int(new_port)
            if port_num < 1 or port_num > 65535:
                QMessageBox.warning(self, "端口错误", "端口号必须在 1-65535 范围内！")
                return
        except ValueError:
            QMessageBox.warning(self, "端口错误", "请输入有效的端口号！")
            return
        
        # 如果端口号有变化，显示警告
        if new_port != self.original_port:
            reply = QMessageBox.warning(
                self,
                "端口更改警告",
                "⚠️ 您正在更改端口号！\n\n"
                "更改后请确保在您的作品中设置相同的端口号，否则无法正常使用。\n\n"
                "是否确定要更改端口号？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                # 恢复原来的端口号
                self.port_edit.setText(self.original_port)
                return
        
        self.accept()
    
    def get_settings(self):
        return {
            "cache_dir": self.cache_edit.text(),
            "host": self.host_edit.text(),
            "port": self.port_edit.text()
        }
    
    def set_settings(self, settings):
        self.cache_edit.setText(settings.get("cache_dir", ""))
        self.host_edit.setText(settings.get("host", "127.0.0.1"))
        self.port_edit.setText(settings.get("port", "5000"))
        # 保存原始端口号用于比较
        self.original_port = settings.get("port", "5000")

class MusicMetadataApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.tray_icon = None
        self.server_thread = None
        self.server_process = None
        self.settings = {}
        self.load_settings()
        
        self.init_ui()
        self.init_tray()
        
        # 启动服务器
        self.start_server()
    
    def get_icon(self):
        """获取图标，支持开发环境和打包环境"""
        # 使用资源路径函数获取图标
        icon_path = resource_path("icon.ico")
        
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        
        # 如果都找不到，返回默认图标
        return self.style().standardIcon(QStyle.SP_ComputerIcon)
    
    def load_settings(self):
        # 从配置文件加载设置
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        default_settings = {
            "cache_dir": os.path.join(os.path.expanduser("~"), "MusicCache"),
            "host": "127.0.0.1",  # 固定为本地主机
            "port": "5000",
            "minimize_to_tray": True
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_settings = json.load(f)
                    # 确保host始终为127.0.0.1，不允许更改
                    loaded_settings["host"] = "127.0.0.1"
                    self.settings = loaded_settings
            except:
                self.settings = default_settings
        else:
            self.settings = default_settings
            self.save_settings()
    
    def save_settings(self):
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        # 确保host始终为127.0.0.1
        self.settings["host"] = "127.0.0.1"
        with open(config_path, 'w') as f:
            json.dump(self.settings, f, indent=4)
    
    def init_ui(self):
        self.setWindowTitle("Metadata Processing Server")
        self.setGeometry(300, 300, 500, 400)
        
        # 设置窗口图标
        self.setWindowIcon(self.get_icon())
        
        # 创建中央部件
        central_widget = QTextEdit()
        central_widget.setReadOnly(True)
        central_widget.setPlaceholderText("服务器日志将显示在这里...")
        self.setCentralWidget(central_widget)
        
        # 创建状态栏
        self.statusBar().showMessage("服务器未运行")
        
        # 创建菜单栏
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)
        
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.quit_application)
        file_menu.addAction(exit_action)
        
        # 服务器菜单
        server_menu = menubar.addMenu("服务器")
        
        start_action = QAction("启动服务器", self)
        start_action.triggered.connect(self.start_server)
        server_menu.addAction(start_action)
        
        stop_action = QAction("停止服务器", self)
        stop_action.triggered.connect(self.stop_server)
        server_menu.addAction(stop_action)
        
        restart_action = QAction("重启服务器", self)
        restart_action.triggered.connect(self.restart_server)
        server_menu.addAction(restart_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("视图")
        
        self.minimize_to_tray_action = QAction("最小化到系统托盘", self, checkable=True)
        self.minimize_to_tray_action.setChecked(self.settings.get("minimize_to_tray", True))
        self.minimize_to_tray_action.triggered.connect(self.toggle_minimize_to_tray)
        view_menu.addAction(self.minimize_to_tray_action)
    
    def init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        
        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.get_icon())
        self.tray_icon.setToolTip("Metadata Processing Server")
        
        # 创建托盘菜单
        tray_menu = QMenu()
        
        show_action = QAction("显示", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)
        
        hide_action = QAction("隐藏", self)
        hide_action.triggered.connect(self.hide)
        tray_menu.addAction(hide_action)
        
        tray_menu.addSeparator()
        
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.show_settings)
        tray_menu.addAction(settings_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()
    
    def toggle_minimize_to_tray(self, checked):
        self.settings["minimize_to_tray"] = checked
        self.save_settings()
    
    def show_settings(self):
        dialog = SettingsDialog(self)
        dialog.set_settings(self.settings)
        
        if dialog.exec():
            new_settings = dialog.get_settings()
            self.settings.update(new_settings)
            self.save_settings()
            
            # 显示端口更改成功提示
            if new_settings.get("port") != dialog.original_port:
                QMessageBox.information(
                    self,
                    "端口更改成功",
                    f"端口号已更改为: {new_settings['port']}\n\n"
                    "请确保在您的作品中设置相同的端口号，否则无法正常使用。"
                )
            
            # 重启服务器以应用新设置
            self.restart_server()
    
    def start_server(self):
        # 确保缓存目录存在
        cache_dir = self.settings.get("cache_dir", "")
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        
        # 启动服务器线程
        if self.server_thread and self.server_thread.is_alive():
            self.statusBar().showMessage("服务器已在运行")
            return
        
        try:
            # 导入并启动服务器
            from server_main import run_server
            self.server_thread = threading.Thread(
                target=run_server,
                args=(self.settings["host"], int(self.settings["port"]), cache_dir),
                daemon=True
            )
            self.server_thread.start()
            
            server_url = f"http://{self.settings['host']}:{self.settings['port']}"
            self.statusBar().showMessage(f"服务器运行在 {server_url}")
            
            # 添加日志
            self.centralWidget().append(f"服务器启动成功 - {server_url}")
            self.centralWidget().append("主机地址固定为: 127.0.0.1 (localhost)")
            self.centralWidget().append(f"端口号: {self.settings['port']}")
            self.centralWidget().append("请在作品中设置相同的端口号")
            
        except Exception as e:
            self.statusBar().showMessage(f"服务器启动失败: {str(e)}")
            self.centralWidget().append(f"错误: {str(e)}")
    
    def stop_server(self):
        # 停止服务器
        try:
            # 发送关闭请求
            url = f"http://{self.settings['host']}:{self.settings['port']}/shutdown"
            requests.post(url, timeout=2)
            self.statusBar().showMessage("服务器已停止")
            self.centralWidget().append("服务器已停止")
        except:
            self.statusBar().showMessage("停止服务器失败")
            self.centralWidget().append("停止服务器失败")
    
    def restart_server(self):
        self.stop_server()
        # 等待一段时间后重启
        QTimer.singleShot(1000, self.start_server)
    
    def closeEvent(self, event):
        if self.settings.get("minimize_to_tray", True) and self.tray_icon:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Metadata Processing Server",
                "应用程序已最小化到系统托盘",
                QSystemTrayIcon.Information,
                2000
            )
        else:
            self.quit_application()
    
    def quit_application(self):
        self.stop_server()
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()

def main():
    # 隐藏控制台窗口
    import ctypes
    if hasattr(ctypes, 'windll'):
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # 设置应用程序图标
    icon_path = resource_path("icon.ico")
    
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    window = MusicMetadataApp()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()