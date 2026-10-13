"""Windows desktop host for the local library and configured remote vision API."""
import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path


class DesktopAPI:
    def __init__(self):
        self._window = None

    def choose_pdfs(self):
        import webview
        return list(self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                    file_types=('PDF files (*.pdf)',)) or [])

    def choose_folder(self):
        import webview
        from backend.main import configured_folder
        from backend.database import connect
        with connect() as c:
            directory = configured_folder(c)
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=directory or str(Path.home() / 'Documents'))
        return result[0] if result else None

    def open_chatgpt(self):
        import webbrowser
        webbrowser.open('https://chatgpt.com/')
        return True

    def open_pdf(self, paper_id):
        from backend.database import connect
        from backend.archive_service import archived_pdf
        from backend.pdf_service import file_hash
        with connect() as c:
            paper = c.execute('SELECT file_hash FROM papers WHERE id=?', (int(paper_id),)).fetchone()
            if not paper:
                raise ValueError('文献不存在')
            snapshot = archived_pdf(paper['file_hash'])
            if snapshot.is_file():
                os.startfile(str(snapshot))
                return True
            for row in c.execute('SELECT path FROM files WHERE paper_id=?', (int(paper_id),)):
                path = Path(row[0])
                if path.is_file() and path.suffix.lower() == '.pdf' and file_hash(path) == paper['file_hash']:
                    os.startfile(str(path))
                    return True
        raise ValueError('PDF 已移动或不可访问，请更新文献库')

    def save_bundle(self, paper_id):
        import webview
        from backend.main import chat_bundle
        response = chat_bundle(int(paper_id))
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f'paper-{int(paper_id)}-chat.zip')
        if not result:
            return None
        Path(result[0]).write_bytes(response.body)
        return result[0]

    def save_text(self, name, text):
        import webview
        name = Path(name).name
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name)
        if not result:
            return None
        target = Path(result[0])
        target.write_text(text, encoding='utf-8')
        return str(target)


def serve():
    import uvicorn
    from backend.main import app
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if not thread.is_alive() or time.monotonic() >= deadline:
            server.should_exit = True
            raise RuntimeError('本地服务未能启动，请查看 data/desktop-error.log')
        time.sleep(.05)
    return server, thread, f'http://127.0.0.1:{port}'


def run_app():
    # Win11 uses the system Edge WebView2 runtime. No browser/console window is required.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    server, thread, url = serve()
    try:
        if '--validation-server' in sys.argv:
            # Isolated packaged-app regression runner. Never runs against the real user's profile.
            if not os.environ.get('LITERATURE_VALIDATION_CONTROL'):
                raise RuntimeError('验证服务必须指定隔离的控制目录')
            control = Path(os.environ['LITERATURE_VALIDATION_CONTROL'])
            control.mkdir(parents=True, exist_ok=True)
            (control / 'server.json').write_text(json.dumps({'url': url}), encoding='utf-8')
            deadline = time.monotonic() + 600
            while not (control / 'stop').exists() and time.monotonic() < deadline:
                time.sleep(.1)
            return
        if '--smoke-test' in sys.argv:
            with urllib.request.urlopen(url + '/api/settings', timeout=5) as response:
                settings = json.load(response)
            result = {'started': True, 'api_calls': settings['api_calls'], 'default_folder': settings['default_folder'], 'pending': settings['pending']}
            target = Path(os.environ.get('LITERATURE_SMOKE_REPORT', 'desktop-smoke.json'))
            target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            return
        import webview
        api = DesktopAPI()
        gui_smoke = '--gui-smoke-test' in sys.argv
        api._window = webview.create_window('PaperTag Local · 研读', url, js_api=api, width=1360, height=880, min_size=(1000, 650), text_select=True, minimized=gui_smoke, focus=not gui_smoke)
        check_errors = []
        def check_gui():
            try:
                if not api._window.events.loaded.wait(25):
                    raise RuntimeError('WebView2 页面未加载')
                deadline = time.monotonic() + 15
                result = None
                while time.monotonic() < deadline:
                    result = api._window.evaluate_js("({title:document.title,bridge:!!window.pywebview?.api?.choose_pdfs,login:!!document.querySelector('#chatLogin'),update:!!document.querySelector('#updateLibrary'),labels:document.querySelectorAll('#filters input').length,facetsReady:!!document.querySelector('#filters .muted')||document.querySelectorAll('#filters input').length>0,defaultFolder:document.querySelector('#folderPath').value})")
                    if result and result['bridge'] and result['facetsReady']:
                        break
                    time.sleep(.1)
                if not result or not result['bridge'] or not result['facetsReady']:
                    raise RuntimeError('桌面桥接或标签界面未就绪')
                api._window.evaluate_js('openAPIConfiguration(); true')
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    api_ui = api._window.evaluate_js("({button:document.querySelector('#chatLogin').textContent,open:document.querySelector('#apiConfigDialog').open,providers:document.querySelectorAll('#apiProvider option').length,model:document.querySelector('#apiProfileModel').value,secretEmpty:document.querySelector('#apiSecret').value==='',pauseAll:document.querySelector('#pauseAllAI')?.textContent,resumeAll:document.querySelector('#resumeAllAI')?.textContent} )")
                    if api_ui['open'] and api_ui['providers'] == 4:
                        break
                    time.sleep(.1)
                if not api_ui['open'] or api_ui['providers'] != 4 or api_ui['button'] != 'API 配置' or api_ui['pauseAll'] != '全部暂停':
                    raise RuntimeError('API 配置界面未就绪')
                result['api_ui'] = api_ui
                api._window.evaluate_js("document.querySelector('#apiConfigDialog').close();showPage('import');true")
                result['recheck_ui'] = api._window.evaluate_js("({button:document.querySelector('#recheckAllAI').textContent,visible:document.querySelector('#recheckAllAI').getBoundingClientRect().width>0,filters:document.querySelectorAll('#aiJobView option').length})")
                if not result['recheck_ui']['visible'] or result['recheck_ui']['filters'] != 4:
                    raise RuntimeError('顶部重新校验或任务筛选界面未就绪')
                if os.environ.get('LITERATURE_GUI_CHECK_PARTIAL') == '1':
                    api._window.evaluate_js("showPage('library');const partialPaper=state.papers.find(p=>p.status==='partial_result');if(partialPaper)loadDetail(partialPaper.id);true")
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        partial_ui = api._window.evaluate_js("({visible:!!document.querySelector('#detail .warning strong')?.textContent.includes('部分结果'),issues:state.detail?.analysis?._validation_issues?.length||0})")
                        if partial_ui['visible'] and partial_ui['issues']:
                            break
                        time.sleep(.1)
                    if not partial_ui['visible'] or not partial_ui['issues']:
                        raise RuntimeError('部分保存警告未显示')
                    result['partial_ui'] = partial_ui
                target = Path(os.environ.get('LITERATURE_SMOKE_REPORT', 'desktop-smoke.json'))
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as exc:
                check_errors.append(exc)
            finally:
                api._window.destroy()
        webview.start(check_gui if gui_smoke else None, gui='edgechrom', debug=False)
        if check_errors:
            raise check_errors[0]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def main():
    from backend.database import DB_PATH
    from backend.instance_lock import InstanceLock
    instance = InstanceLock(DB_PATH.parent)
    instance.acquire()
    try:
        run_app()
    finally:
        instance.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        from backend.instance_lock import AlreadyRunning
        exception = sys.exc_info()[1]
        if isinstance(exception, AlreadyRunning):
            if not any(flag in sys.argv for flag in ('--smoke-test', '--gui-smoke-test', '--validation-server')):
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, str(exception), '研读', 64)
            sys.exit(1)
        from backend.database import DATA_ROOT
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        (DATA_ROOT / 'desktop-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        if not any(flag in sys.argv for flag in ('--smoke-test', '--gui-smoke-test', '--validation-server')):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f'启动失败。请查看 {DATA_ROOT / "desktop-error.log"}\nWin11 需安装 Microsoft Edge WebView2 Runtime。', '研读', 16)
        sys.exit(1)
