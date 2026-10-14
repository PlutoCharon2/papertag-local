"""WinForms tray lifecycle on the existing WebView2 UI thread."""
import json
import os
import threading
from pathlib import Path


class DesktopTray:
    def __init__(self, window, data_folder: Path):
        self.window = window
        self.ready = threading.Event()
        self.error = None
        self.icon = None
        self.exiting = False
        self.activation_file = data_folder / 'desktop-window.json'
        self.activation_request = data_folder / 'desktop-show.request'
        self.timer = None

    def invoke(self, callback):
        from System import Action
        form = self.window.native
        if form.InvokeRequired:
            form.Invoke(Action(callback))
        else:
            callback()

    def install(self):
        try:
            self.invoke(self._install)
        except Exception as error:
            self.error = error
        finally:
            self.ready.set()

    def _install(self):
        from System.Drawing import Icon, SystemIcons
        from System.Windows.Forms import NotifyIcon, ContextMenuStrip, ToolStripMenuItem, Timer
        menu = ContextMenuStrip()
        self.open_item = ToolStripMenuItem('打开文献库')
        self.exit_item = ToolStripMenuItem('退出软件')
        self.open_item.Click += self.show
        self.exit_item.Click += self.exit
        menu.Items.Add(self.open_item)
        menu.Items.Add(self.exit_item)
        self.icon = NotifyIcon()
        self.icon.Text = '垃圾桶 · 科研文献库'
        self.icon.Icon = Icon.ExtractAssociatedIcon(os.sys.executable) or SystemIcons.Application
        self.icon.ContextMenuStrip = menu
        self.icon.DoubleClick += self.show
        self.icon.Visible = True
        self.window.native.FormClosing += self.on_closing
        self.window.native.FormClosed += self.on_closed
        self.activation_file.write_text(json.dumps({'pid': os.getpid(), 'hwnd': self.window.native.Handle.ToInt64()}), encoding='utf-8')
        self.activation_request.unlink(missing_ok=True)
        self.timer = Timer()
        self.timer.Interval = 250
        self.timer.Tick += self.check_activation
        self.timer.Start()

    def check_activation(self, *args):
        if self.activation_request.exists():
            self.activation_request.unlink(missing_ok=True)
            self.show()

    def on_closing(self, sender, event):
        from System.Windows.Forms import CloseReason
        if not self.exiting and event.CloseReason == CloseReason.UserClosing and self.icon and self.icon.Visible:
            event.Cancel = True
            sender.Hide()

    def show(self, *args):
        def restore():
            from System.Windows.Forms import FormWindowState
            form = self.window.native
            form.Show()
            if form.WindowState == FormWindowState.Minimized:
                form.WindowState = FormWindowState.Normal
            form.Activate()
        self.invoke(restore)

    def exit(self, *args):
        def close():
            self.exiting = True
            self.dispose()
            self.window.native.Close()
        self.invoke(close)

    def on_closed(self, *args):
        self.dispose()

    def dispose(self):
        if self.timer:
            self.timer.Stop()
            self.timer.Dispose()
            self.timer = None
        if self.icon:
            self.icon.Visible = False
            self.icon.Dispose()
            self.icon = None
        self.activation_file.unlink(missing_ok=True)
        self.activation_request.unlink(missing_ok=True)


def restore_existing_window(data_folder: Path):
    """Only activate the verified process/window belonging to this data folder."""
    try:
        import ctypes
        from ctypes import wintypes
        data = json.loads((data_folder / 'desktop-window.json').read_text(encoding='utf-8'))
        user32 = ctypes.windll.user32
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        hwnd = data['hwnd']
        owner = wintypes.DWORD()
        if not user32.IsWindow(hwnd):
            return False
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != data['pid']:
            return False
        # Let the owning UI thread restore managed visibility and window state.
        (data_folder / 'desktop-show.request').write_text('show', encoding='utf-8')
        return True
    except (OSError, ValueError, KeyError):
        return False
