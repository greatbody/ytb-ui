import sys
import subprocess
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTextEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QCheckBox, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
import os
CONFIG_FILE = os.path.join(os.path.dirname(__file__), ".ytb_gui_config")

class YtDlpWorker(QThread):
    output = Signal(str)
    finished = Signal()

    def __init__(self, urls, cookies_path):
        super().__init__()
        self.urls = urls
        self.cookies_path = cookies_path
        self._process = None
        self._should_stop = False
        self.stopped_by_user = False  # Add this flag

    def run(self):
        for url in self.urls:
            url = url.strip()
            if not url:
                continue
            cmd = [
                'yt-dlp',
                '-4',  # Force IPv4
                '-f', 'bestvideo+bestaudio',
                '--merge-output-format', 'mp4',
            ]
            if self.cookies_path:
                cmd += ['--cookies', self.cookies_path]
            cmd += ['-o', '%(playlist_index)s - %(title)s.%(ext)s', url]
            try:
                self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in self._process.stdout:
                    if self._should_stop:
                        break
                    self.output.emit(line)
                if self._should_stop and self._process.poll() is None:
                    self._process.terminate()
                self._process.wait()
            except Exception as e:
                self.output.emit(f"Error: {e}\n")

    def stop(self):
        self._should_stop = True
        self.stopped_by_user = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube下载器 (yt-dlp)")
        self.resize(600, 400)
        layout = QVBoxLayout()

        self.url_label = QLabel("粘贴YouTube链接（每行一个）：")
        layout.addWidget(self.url_label)

        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/playlist?list=...")
        self.url_input.setMaximumHeight(80)
        layout.addWidget(self.url_input)

        self.cookie_label = QLabel("拖拽cookie文件到下方（可选）：")
        layout.addWidget(self.cookie_label)

        self.cookie_box = QLabel("将cookie文件拖到这里或点击选择")
        self.cookie_box.setStyleSheet("QLabel { border: 2px dashed #aaa; padding: 20px; }")
        self.cookie_box.setAlignment(Qt.AlignCenter)
        self.cookie_box.setAcceptDrops(True)
        self.cookie_box.installEventFilter(self)
        layout.addWidget(self.cookie_box)
        self.cookie_path = None

        self.load_last_cookie_path()

        self.auto_exit_checkbox = QCheckBox("下载完成后自动退出")
        self.auto_exit_checkbox.setChecked(True)
        layout.addWidget(self.auto_exit_checkbox)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('下载进度: %p%')
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.start_button = QPushButton("开始下载")
        self.start_button.clicked.connect(self.start_download)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("停止下载")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_download)
        layout.addWidget(self.stop_button)

        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        layout.addWidget(self.output_box)

        self.setLayout(layout)
        self.playlist_total = None
        self.playlist_current = None

    def load_last_cookie_path(self):
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    path = f.read().strip()
                    if path and os.path.isfile(path):
                        self.cookie_path = path
                        self.cookie_box.setText(f"Cookie文件: {os.path.basename(path)}")
            except Exception:
                pass

    def save_last_cookie_path(self, file_path):
        try:
            with open(CONFIG_FILE, "w") as f:
                f.write(file_path)
        except Exception:
            pass

    def set_cookie_file(self, file_path):
        if os.path.isfile(file_path):
            self.cookie_path = file_path
            self.cookie_box.setText(f"Cookie文件: {os.path.basename(file_path)}")
            self.save_last_cookie_path(file_path)
        else:
            QMessageBox.warning(self, "无效文件", "请选择一个有效的文件。")

    def select_cookie_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择Cookie文件", os.path.expanduser("~"), "文本文件 (*.txt);;所有文件 (*)")
        if file_path:
            self.set_cookie_file(file_path)

    def start_download(self):
        urls = self.url_input.toPlainText().splitlines()
        if not any(url.strip() for url in urls):
            QMessageBox.warning(self, "无链接", "请至少输入一个YouTube链接。")
            return
        self.output_box.clear()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.worker = YtDlpWorker(urls, self.cookie_path)
        self.worker.output.connect(self.append_output)
        self.worker.finished.connect(self.download_finished)
        self.worker.start()

    def stop_download(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stopped_by_user = True
            self.worker.stop()
            self.output_box.append("\n已请求停止下载。请稍候...")
        self.stop_button.setEnabled(False)

    def append_output(self, text):
        self.output_box.append(text)
        import re
        # Detect playlist progress: [download] Downloading item X of Y
        playlist_match = re.search(r'\[download\] Downloading item (\d+) of (\d+)', text)
        if playlist_match:
            self.playlist_current = int(playlist_match.group(1))
            self.playlist_total = int(playlist_match.group(2))
            percent = int(self.playlist_current / self.playlist_total * 100)
            self.progress_bar.setValue(percent)
            return
        # Detect per-file progress only if not in playlist mode
        if self.playlist_total:
            # If we are in playlist mode, ignore per-file progress
            return
        # yt-dlp progress lines look like: [download]  12.3% of ...
        match = re.search(r'\[download\]\s+(\d{1,3}\.\d+)%', text)
        if match:
            percent = float(match.group(1))
            self.progress_bar.setValue(int(percent))
        elif '[download] Destination:' in text or '[download] Downloading item' in text:
            self.progress_bar.setValue(0)
        elif '[download] 100%' in text or 'has already been downloaded' in text:
            self.progress_bar.setValue(100)

    def download_finished(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        if hasattr(self, 'worker') and getattr(self.worker, 'stopped_by_user', False):
            self.output_box.append("\n下载已被用户停止。")
        else:
            self.output_box.append("\n下载完成。")
            if self.auto_exit_checkbox.isChecked():
                QApplication.quit()

    def eventFilter(self, source, event):
        from PySide6.QtCore import QEvent
        if source == self.cookie_box:
            if event.type() == QEvent.DragEnter:
                if event.mimeData().hasUrls():
                    event.accept()
                    return True
            elif event.type() == QEvent.Drop:
                urls = event.mimeData().urls()
                if urls:
                    file_path = urls[0].toLocalFile()
                    self.set_cookie_file(file_path)
                return True
            elif event.type() == QEvent.MouseButtonRelease:
                self.select_cookie_file()
                return True
        return super().eventFilter(source, event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
