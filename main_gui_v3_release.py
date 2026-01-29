import sys
import os
import subprocess
import json
import re
import ctypes
import time
import traceback
from pathlib import Path

# 确保 PyQt6 环境完整
try:
    from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                                 QLineEdit, QPushButton, QProgressBar, QTextEdit,
                                 QLabel, QFileDialog, QSystemTrayIcon, QMenu, QStyle, QMessageBox)
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent, QSize
    from PyQt6.QtGui import QIcon, QTextCursor, QFont, QPalette, QColor, QAction
except ImportError:
    print("环境错误：请执行 pip install PyQt6")
    sys.exit(1)

# ==========================================
# 0. Windows 任务栏与系统设置
# ==========================================
try:
    # 设置唯一的 AppID 确保 Windows 任务栏合并图标正确
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        've.wallpaper.v3.3.final')
except:
    pass


def get_resource_path(relative_path):
    """ 处理打包后的资源释放路径 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ==========================================
# 1. 核心处理线程 (含卡死监控与缓冲区修补)
# ==========================================


class VideoWorker(QThread):
    log_signal = pyqtSignal(str)          # 日志回调
    total_progress_signal = pyqtSignal(int)  # 进度条回调
    error_signal = pyqtSignal(str)        # 报错回调
    finished_signal = pyqtSignal()        # 完成回调

    def __init__(self, work_dir):
        super().__init__()
        self.work_dir = Path(work_dir)
        self.is_running = True
        self.ffmpeg_path = None
        self.ffprobe_path = None

    def find_ffmpeg(self):
        """ 搜索当前目录下的 FFmpeg 组件 """
        base_path = Path(sys.executable).parent if getattr(
            sys, 'frozen', False) else Path(__file__).parent.resolve()
        for p in base_path.rglob("*.exe"):
            if p.name.lower() == "ffmpeg.exe":
                self.ffmpeg_path = str(p)
            elif p.name.lower() == "ffprobe.exe":
                self.ffprobe_path = str(p)

        import shutil
        if not self.ffmpeg_path:
            self.ffmpeg_path = shutil.which("ffmpeg")
        if not self.ffprobe_path:
            self.ffprobe_path = shutil.which("ffprobe")

    def create_progress_bar_text(self, percent, length=35):
        """ 信息区模拟进度条 """
        filled_len = int(length * percent // 100)
        bar = '█' * filled_len + '░' * (length - filled_len)
        return f"|{bar}| {percent}%"

    def run_ffmpeg_task(self, cmd, total_frames):
        """ 关键：带看门狗与行缓冲的执行逻辑 """
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # 合并 stderr 解决缓冲区卡死
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore',
            bufsize=1,
            startupinfo=si
        )

        last_frame_count = -1
        last_active_time = time.time()

        while True:
            if not self.is_running:
                process.terminate()
                return False

            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break

            if 'frame=' in line:
                match = re.search(r'frame=\s*(\d+)', line)
                if match:
                    current_frame = int(match.group(1))
                    if current_frame != last_frame_count:
                        last_frame_count = current_frame
                        last_active_time = time.time()
                        if total_frames > 0:
                            pct = min(
                                100, int(current_frame * 100 / total_frames))
                            self.log_signal.emit(
                                f"\r{self.create_progress_bar_text(pct)}")

            # 看门狗：25 秒进度不动则判定为驱动卡死
            if time.time() - last_active_time > 25:
                self.log_signal.emit("\n[!] 警告：发现进度卡滞，正在强制干预...")
                process.terminate()
                return False

        return process.returncode == 0

    def run(self):
        try:
            self.find_ffmpeg()
            if not self.ffmpeg_path:
                self.error_signal.emit("致命错误：未找到 ffmpeg.exe。")
                return

            exts = ('.mp4', '.mov', '.mkv', '.avi', '.wmv')
            videos = [f for f in self.work_dir.iterdir()
                      if f.suffix.lower() in exts]

            if not videos:
                self.log_signal.emit(">>> 目录下没有发现任何视频文件。")
                self.finished_signal.emit()
                return

            total_sub_tasks = len(videos) * 2
            completed_tasks = 0

            self.log_signal.emit(f"=== 引擎启动：发现 {len(videos)} 个视频 ===\n")

            for v_path in videos:
                if not self.is_running:
                    break

                # 获取元数据
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                probe_cmd = [self.ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
                             '-show_entries', 'stream=width,height,nb_frames', '-of', 'json', str(v_path)]
                meta_data = json.loads(subprocess.check_output(
                    probe_cmd, startupinfo=si).decode('utf-8'))['streams'][0]

                raw_w, raw_h = int(meta_data['width']), int(
                    meta_data['height'])
                total_f = int(meta_data.get('nb_frames', 0))

                # 旋转判定
                is_landscape = raw_w > raw_h
                w, h = (raw_h, raw_w) if is_landscape else (raw_w, raw_h)

                for label, ratio in [('9x20', 9/20), ('5x11', 5/11)]:
                    if not self.is_running:
                        break

                    target_h = int(w / ratio)
                    output_folder = self.work_dir / "output" / label
                    output_folder.mkdir(parents=True, exist_ok=True)
                    target_file = output_folder / v_path.name

                    # 滤镜参数计算
                    sw, sh, sth = (w//2)*2, (h//2)*2, (target_h//2)*2
                    y_off = (sth - sh) // 2
                    trans = "transpose=1" if is_landscape else "copy"

                    filter_str = (
                        f"[0:v]{trans},setsar=1[raw];[raw]split=2[bg_s][fg_s];"
                        f"[bg_s]scale={sw}:{sth}:force_original_aspect_ratio=increase,crop={sw}:{sth},gblur=sigma=20[bg];"
                        f"color=c=white:s={sw}x{sh}[m_base];[m_base]drawbox=x=0:y=0:w={sw}:h=30:t=fill:c=black,"
                        f"drawbox=x=0:y={sh-30}:w={sw}:h=30:t=fill:c=black,drawbox=x=0:y=0:w=30:h={sh}:t=fill:c=black,"
                        f"drawbox=x={sw-30}:y=0:w=30:h={sh}:t=fill:c=black,boxblur=30:1,format=gray[mask];"
                        f"[fg_s]format=yuva420p[fg_a];[fg_a][mask]alphamerge[fg_f];"
                        f"[bg][fg_f]overlay=x=0:y={y_off}:shortest=1:format=auto,format=yuv420p[outv]"
                    )

                    self.log_signal.emit(f"\n[处理] {v_path.name} | 模式: {label}")

                    # 1. 优先 GPU
                    cmd_gpu = [
                        self.ffmpeg_path, '-y', '-progress', 'pipe:1', '-i', str(
                            v_path),
                        '-filter_complex', filter_str, '-map', '[outv]',
                        '-c:v', 'h264_nvenc', '-preset', 'p4', '-rc:v', 'vbr', '-b:v', '10M',
                        '-map', '0:a?', '-c:a', 'copy', str(target_file)
                    ]

                    success = self.run_ffmpeg_task(cmd_gpu, total_f)

                    if not success:
                        # 2. 备选 CPU
                        self.log_signal.emit("\n[!] GPU 模式失败，切换 CPU 安全模式渲染...")
                        cmd_cpu = [
                            self.ffmpeg_path, '-y', '-progress', 'pipe:1', '-i', str(
                                v_path),
                            '-filter_complex', filter_str, '-map', '[outv]',
                            '-c:v', 'libx264', '-preset', 'veryfast',
                            '-map', '0:a?', '-c:a', 'copy', str(target_file)
                        ]
                        self.run_ffmpeg_task(cmd_cpu, total_f)

                    self.log_signal.emit("\n[√] 该任务比例合成完毕")
                    completed_tasks += 1
                    self.total_progress_signal.emit(
                        int((completed_tasks / total_sub_tasks) * 100))

            self.log_signal.emit("\n>>> 全部批量视频合成任务已顺利结束！\n")
            self.finished_signal.emit()

        except Exception:
            self.error_signal.emit(traceback.format_exc())

# ==========================================
# 2. GUI 主界面 (集成托盘监听)
# ==========================================


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VE Wallpaper Engine Double v3.3.1 (Stable)")
        self.resize(800, 600)

        # 图标配置
        self.icon_path = get_resource_path("01.ico")
        if os.path.exists(self.icon_path):
            self.main_icon = QIcon(self.icon_path)
            self.setWindowIcon(self.main_icon)
        else:
            self.main_icon = self.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon)

        # 样式定义 (米白色字体 #DCDCDC)
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #E0E0E0; font-family: 'Consolas', '微软雅黑'; }
            QLineEdit { background-color: #1E1E1E; border: 1px solid #333; padding: 8px; color: #FFFFFF; border-radius: 4px; }
            QPushButton { background-color: #0078D4; color: white; border: none; padding: 12px; font-weight: bold; border-radius: 4px; }
            QPushButton:hover { background-color: #1A8AD9; }
            QPushButton:disabled { background-color: #333333; }
            QProgressBar { border: 1px solid #333; height: 16px; text-align: center; border-radius: 8px; background-color: #1E1E1E; }
            QProgressBar::chunk { background-color: #0078D4; border-radius: 8px; }
            QTextEdit { 
                background-color: #0A0A0A; 
                border: 1px solid #222; 
                color: #DCDCDC;   /* 米白色字体 */
                padding: 10px; 
                border-radius: 4px;
            }
        """)

        self.setup_ui()
        self.setup_tray()
        self.worker = None

    def setup_ui(self):
        """ 构建主界面布局 """
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(15)

        # 路径行
        h_path = QHBoxLayout()
        self.path_field = QLineEdit()
        current_path = str(Path(sys.executable).parent if getattr(
            sys, 'frozen', False) else Path(__file__).parent.resolve())
        self.path_field.setText(current_path)
        btn_dir = QPushButton("📁 浏览目录")
        btn_dir.setFixedWidth(120)
        btn_dir.clicked.connect(self.browse_folder)
        h_path.addWidget(QLabel("工作路径:"))
        h_path.addWidget(self.path_field)
        h_path.addWidget(btn_dir)
        main_layout.addLayout(h_path)

        # 启动键
        self.btn_run = QPushButton("🚀 启动批量引擎")
        self.btn_run.setFixedHeight(45)
        self.btn_run.clicked.connect(self.start_engine)
        main_layout.addWidget(self.btn_run)

        # 进度条
        main_layout.addWidget(QLabel("总任务进度:"))
        self.progress_all = QProgressBar()
        main_layout.addWidget(self.progress_all)

        # 信息反馈区
        main_layout.addWidget(QLabel("执行详细日志:"))
        self.info_box = QTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setFont(QFont("Consolas", 10))
        main_layout.addWidget(self.info_box)

        self.setLayout(main_layout)

    def setup_tray(self):
        """ 配置系统托盘逻辑 """
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.main_icon)
        self.tray.setToolTip("VE 视频处理引擎 - 运行中")

        # 托盘右键菜单
        menu = QMenu()
        act_show = QAction("显示主界面", self)
        act_show.triggered.connect(self.restore_window)

        act_exit = QAction("完全退出", self)
        act_exit.triggered.connect(self.safe_exit)

        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_exit)

        self.tray.setContextMenu(menu)
        # 单击图标恢复
        self.tray.activated.connect(self.on_tray_click)
        self.tray.show()

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.restore_window()

    def restore_window(self):
        """ 从托盘恢复窗口 """
        self.show()
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.activateWindow()

    def changeEvent(self, event):
        """ 捕捉最小化动作 """
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                # 最小化时隐藏窗口
                self.hide()
                self.tray.showMessage(
                    "后台运行", "程序已最小化到托盘，处理仍在继续。", QSystemTrayIcon.MessageIcon.Information, 2000)
        super().changeEvent(event)

    def browse_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择视频存放文件夹")
        if dir_path:
            self.path_field.setText(dir_path)

    def start_engine(self):
        self.btn_run.setEnabled(False)
        self.info_box.clear()
        self.progress_all.setValue(0)

        self.worker = VideoWorker(self.path_field.text())
        self.worker.log_signal.connect(self.log_update)
        self.worker.total_progress_signal.connect(self.progress_all.setValue)
        self.worker.error_signal.connect(
            lambda e: QMessageBox.critical(self, "运行错误", e))
        self.worker.finished_signal.connect(
            lambda: self.btn_run.setEnabled(True))
        self.worker.start()

    def log_update(self, text):
        cursor = self.info_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if text.startswith("\r"):
            cursor.movePosition(
                QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText(text.replace("\r", ""))
        else:
            self.info_box.insertPlainText(text)
        self.info_box.verticalScrollBar().setValue(
            self.info_box.verticalScrollBar().maximum())

    def safe_exit(self):
        """ 确保线程安全关闭 """
        if self.worker and self.worker.isRunning():
            self.worker.is_running = False
            self.worker.wait()
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 强制设置深色调调色板
    dp = QPalette()
    dp.setColor(QPalette.ColorRole.Window, QColor(18, 18, 18))
    app.setPalette(dp)

    gui = MainWindow()
    gui.show()
    sys.exit(app.exec())
