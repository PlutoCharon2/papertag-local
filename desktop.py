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

    def open_original_location(self, paper_id):
        import subprocess
        from backend.database import connect
        with connect() as c:
            paths = [Path(r[0]) for r in c.execute('SELECT path FROM files WHERE paper_id=?', (int(paper_id),))]
        for path in paths:
            if path.is_file() and path.suffix.lower() == '.pdf':
                subprocess.Popen(['explorer.exe', '/select,', str(path.resolve())])
                return True
        raise ValueError('原始PDF已移动或不可访问，请检查本地目录')

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
        api._window = webview.create_window('PaperTag Local · 垃圾桶', url, js_api=api, width=1360, height=880, min_size=(1000, 650), text_select=True, minimized=gui_smoke, focus=not gui_smoke)
        tray = None
        if not gui_smoke or os.environ.get('LITERATURE_GUI_CHECK_TRAY') == '1':
            from backend.database import DATA_ROOT
            from desktop_tray import DesktopTray
            tray = DesktopTray(api._window, DATA_ROOT)
            api._window.events.shown += tray.install
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
                if os.environ.get('LITERATURE_GUI_CHECK_REFRESH') == '1':
                    api._window.evaluate_js("showPage('settings');true")
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        refresh_ui = api._window.evaluate_js("({nav:document.querySelector('nav [data-page=\"settings\"]').textContent,minutes:document.querySelector('#refreshMinutes')?.value,enabled:document.querySelector('#refreshEnabled')?.checked,button:document.querySelector('#updateLibrary').textContent})")
                        if refresh_ui.get('minutes') == '20' and refresh_ui.get('enabled'):
                            break
                        time.sleep(.1)
                    if refresh_ui.get('nav') != '设置' or refresh_ui.get('minutes') != '20' or refresh_ui.get('button') != '检查新增':
                        raise RuntimeError('刷新设置界面未就绪')
                    api._window.evaluate_js("document.querySelector('#refreshMinutes').value='45';document.querySelector('#refreshSettingsForm').requestSubmit();true")
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        with urllib.request.urlopen(url + '/api/refresh/settings', timeout=5) as response:
                            saved = json.load(response)
                        if saved['interval_minutes'] == 45:
                            break
                        time.sleep(.1)
                    if saved['interval_minutes'] != 45:
                        raise RuntimeError('刷新间隔未保存')
                    api._window.evaluate_js("showPage('library');document.querySelector('#updateLibrary').click();true")
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        scan_ui = api._window.evaluate_js("({status:document.querySelector('#libraryRefreshStatus').textContent,years:document.querySelectorAll('.publication-year').length,venues:document.querySelectorAll('.publication-venue').length,count:document.querySelector('#count').textContent})")
                        if scan_ui.get('count') == '1' and '上次检查' in scan_ui.get('status', ''):
                            break
                        time.sleep(.2)
                    if scan_ui.get('count') != '1' or scan_ui.get('years') != 1 or scan_ui.get('venues') != 1:
                        raise RuntimeError('手动刷新或发表信息标签未生效')
                    combined_ui = api._window.evaluate_js("({combined:!!document.querySelector('#checkNewAI'),oldPending:!!document.querySelector('#queuePending'),oldRefresh:!!document.querySelector('#refreshAI'),title:document.querySelector('.paper-card h3').textContent})")
                    if not combined_ui['combined'] or combined_ui['oldPending'] or combined_ui['oldRefresh'] or combined_ui['title'].startswith('[2026]'):
                        raise RuntimeError('合并入口、删除状态刷新按钮或标题显示未生效')
                    result['library_refresh'] = {'defaults': refresh_ui, 'saved': saved, 'manual_scan': scan_ui}
                    result['library_refresh']['combined_ui'] = combined_ui
                    with urllib.request.urlopen(url + '/api/ai/queue', timeout=5) as response:
                        queue = json.load(response)
                    if queue.get('queued') != 1:
                        raise RuntimeError('检查新增没有将新论文加入分析队列')
                    toggle_states = []
                    for expected in ['继续分析', '全部暂停']:
                        api._window.evaluate_js("document.querySelector('#pauseAllAI').click();true")
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            toggle = api._window.evaluate_js("({text:document.querySelector('#pauseAllAI').textContent,disabled:document.querySelector('#pauseAllAI').disabled,single:!document.querySelector('#resumeAllAI')})")
                            if toggle['text'] == expected and not toggle['disabled']:
                                break
                            time.sleep(.1)
                        if toggle['text'] != expected or not toggle['single'] or toggle['disabled']:
                            raise RuntimeError('合并后的暂停/继续按钮未正确切换')
                        toggle_states.append(toggle)
                    result['library_refresh']['queue'] = queue
                    result['library_refresh']['toggle_states'] = toggle_states
                    if os.environ.get('LITERATURE_GUI_TEST_SOURCE'):
                        from backend.database import DATA_ROOT as refresh_test_root
                        source = Path(os.environ['LITERATURE_GUI_TEST_SOURCE']).resolve()
                        if not source.is_relative_to(refresh_test_root.parent.resolve()):
                            raise RuntimeError('GUI测试源文件不在隔离测试目录')
                        source.unlink()
                        api._window.evaluate_js("showPage('import');document.querySelector('#checkNewAI').click();true")
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            deleted_ui = api._window.evaluate_js("({count:document.querySelector('#count').textContent,status:document.querySelector('#libraryRefreshStatus').textContent})")
                            if deleted_ui['count'] == '0' and '已移除 1' in deleted_ui['status']:
                                break
                            time.sleep(.2)
                        if deleted_ui['count'] != '0' or '已移除 1' not in deleted_ui['status']:
                            raise RuntimeError('合并入口检查后没有移除本地已删除文献')
                        result['library_refresh']['deleted_ui'] = deleted_ui
                api._window.evaluate_js('openAPIConfiguration(); true')
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    api_ui = api._window.evaluate_js("({button:document.querySelector('#chatLogin').textContent,open:document.querySelector('#apiConfigDialog').open,providers:document.querySelectorAll('#apiProvider option').length,model:document.querySelector('#apiProfileModel').value,secretEmpty:document.querySelector('#apiSecret').value==='',pauseAll:document.querySelector('#pauseAllAI')?.textContent,resumeAllAbsent:!document.querySelector('#resumeAllAI')} )")
                    if api_ui['open'] and api_ui['providers'] == 4:
                        break
                    time.sleep(.1)
                if not api_ui['open'] or api_ui['providers'] != 4 or api_ui['button'] != 'API 配置' or api_ui['pauseAll'] != '全部暂停':
                    raise RuntimeError('API 配置界面未就绪')
                result['api_ui'] = api_ui
                if os.environ.get('LITERATURE_GUI_CHECK_INTERACTIONS') == '1':
                    from desktop_validation import check_interactions
                    result['interactions'] = check_interactions(api._window)
                if os.environ.get('LITERATURE_GUI_CHECK_KEYS') == '1':
                    from desktop_validation import check_keys_and_review
                    result['keys_and_review'] = check_keys_and_review(api._window,url)
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
                if os.environ.get('LITERATURE_GUI_CHECK_READER') == '1':
                    api._window.evaluate_js("showPage('library');loadDetail(state.papers[0].id);true")
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        reader = api._window.evaluate_js("({loaded:!!document.querySelector('#pdfViewerFrame')?.contentWindow?.PDFViewerApplication?.pdfDocument&&document.querySelector('#pdfViewerFrame').contentDocument.querySelectorAll('.textLayer span').length>0,tagsClosed:document.querySelector('#tagReviewDialog')?.open===false,claimsClosed:!document.querySelector('#claimsDialog'),journal:document.querySelector('#detail')?.textContent.toUpperCase().includes('READER TEST JOURNAL')})")
                        if all(reader.values()):
                            break
                        time.sleep(.1)
                    if not all(reader.values()):
                        raise RuntimeError('PDF 阅读器或收起的审核窗口未就绪：' + str(reader))
                    api._window.evaluate_js("document.querySelector('#openTagReview').click();true")
                    if not api._window.evaluate_js("document.querySelector('#tagReviewDialog').open&&document.querySelector('#tagReviewDialog').getBoundingClientRect().width>0"):
                        raise RuntimeError('标签审核按钮无效')
                    api._window.evaluate_js("true")
                    if not api._window.evaluate_js("!!document.querySelector('#tagReviewDialog #reviewClaims')&&!document.querySelector('#openClaims')"):
                        raise RuntimeError('证据按钮无效')
                    api._window.evaluate_js("document.querySelector('#tagReviewDialog').close();state.showPDF(2);true")
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        flipped = api._window.evaluate_js("document.querySelector('#pdfViewerFrame').contentWindow.PDFViewerApplication.page===2&&document.querySelector('#pdfViewerFrame').contentDocument.querySelector('[data-page-number=\"2\"] canvas')?.width>0")
                        if flipped:
                            break
                        time.sleep(.1)
                    if not flipped:
                        raise RuntimeError('PDF 翻页未成功')
                    result['reader_ui'] = dict(reader, tags_button=True, claims_button=True, page_two=True)
                    app_window = "document.querySelector('#pdfViewerFrame').contentWindow"
                    api._window.evaluate_js(f"{app_window}.PDFViewerApplication.pdfDocument.getData().then(bytes=>window.__pdfHeader=String.fromCharCode(...bytes.slice(0,5)));true")
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        if api._window.evaluate_js("window.__pdfHeader==='%PDF-'"):
                            break
                        time.sleep(.1)
                    if not api._window.evaluate_js("window.__pdfHeader==='%PDF-'"):
                        raise RuntimeError('阅读器没有读取原始PDF字节')
                    api._window.evaluate_js(f"{app_window}.PDFViewerApplication.page=1;true")
                    original_width = api._window.evaluate_js("document.querySelector('#pdfViewerFrame').contentDocument.querySelector('[data-page-number=\"1\"] canvas').width")
                    api._window.evaluate_js(f"const pdfViewer={app_window}.PDFViewerApplication.pdfViewer;pdfViewer.currentScale=pdfViewer.currentScale*1.5;true")
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        enlarged = api._window.evaluate_js("document.querySelector('#pdfViewerFrame').contentDocument.querySelector('[data-page-number=\"1\"] canvas').width")
                        if enlarged > original_width:
                            break
                        time.sleep(.1)
                    if enlarged <= original_width:
                        raise RuntimeError('放大没有重新渲染PDF')
                    result['original_pdf_reader'] = {'pdf_header': '%PDF-', 'selectable_text_layer': True, 'pages': 2, 'before_zoom_canvas_width': original_width, 'after_zoom_canvas_width': enlarged}
                    api._window.evaluate_js("window.favoriteReaderFrame=document.querySelector('#pdfViewerFrame');favoriteReaderFrame.contentWindow.PDFViewerApplication.page=2;document.querySelector('.favorite-toggle').click();true")
                    deadline = time.monotonic()+10
                    while time.monotonic()<deadline:
                        if api._window.evaluate_js("document.querySelector('.favorite-toggle').getAttribute('aria-pressed')==='true'&&!document.querySelector('.favorite-toggle').disabled"):
                            break
                        time.sleep(.1)
                    if not api._window.evaluate_js("state.detail.is_favorite&&document.querySelector('.favorite-toggle').nextElementSibling.classList.contains('focus-reading-toggle')&&favoriteReaderFrame===document.querySelector('#pdfViewerFrame')&&favoriteReaderFrame.contentWindow.PDFViewerApplication.page===2"):
                        raise RuntimeError('收藏未保存、星标位置错误或PDF阅读位置被重置')
                    api._window.evaluate_js("document.querySelector('#favoritesOnly').click();true")
                    time.sleep(.3)
                    if not api._window.evaluate_js("document.querySelector('#favoritesOnly').closest('label').nextElementSibling.id==='filters'&&state.papers.length===1&&state.papers[0].is_favorite"):
                        raise RuntimeError('收藏筛选不可用或位置不正确')
                    api._window.evaluate_js("document.querySelector('.favorite-toggle').click();true")
                    deadline = time.monotonic()+10
                    while time.monotonic()<deadline:
                        if api._window.evaluate_js("state.papers.length===0&&!document.querySelector('.favorite-toggle').disabled"):
                            break
                        time.sleep(.1)
                    if not api._window.evaluate_js("state.papers.length===0&&!state.detail.is_favorite&&favoriteReaderFrame===document.querySelector('#pdfViewerFrame')"):
                        raise RuntimeError('取消收藏没有更新筛选或重新加载了PDF')
                    api._window.evaluate_js("document.querySelector('#favoritesOnly').click();true")
                    result['favorites']={'star_before_focus':True,'filter_above_topics':True,'toggle_and_filter':True,'pdf_position_preserved':True}
                    normal = api._window.evaluate_js("(()=>{const frame=document.querySelector('#pdfViewerFrame').getBoundingClientRect();return {width:frame.width,height:frame.height,viewportWidth:innerWidth,viewportHeight:innerHeight,statusHidden:getComputedStyle(document.querySelector('#gptAuthState')).display==='none',offlineHidden:getComputedStyle(document.querySelector('.offline')).display==='none',filtersHidden:document.querySelector('#pendingOnly').closest('label').getBoundingClientRect().width===0&&document.querySelector('#showVersions').closest('label').getBoundingClientRect().width===0,exportsMoved:!!document.querySelector('#exportJSON').closest('#import')&&!!document.querySelector('#exportCSV').closest('#import'),navigation:document.querySelector('nav [data-page=import]').textContent};})()")
                    if not all(normal[k] for k in ('statusHidden','offlineHidden','filtersHidden','exportsMoved')) or normal['navigation']!='导入与导出' or normal['height']<normal['viewportHeight']*.7:
                        raise RuntimeError('紧凑阅读布局不符合要求：'+str(normal))
                    api._window.evaluate_js("document.querySelector('.focus-reading-toggle').click();true")
                    time.sleep(.2)
                    focused = api._window.evaluate_js("(()=>{const frame=document.querySelector('#pdfViewerFrame').getBoundingClientRect();return {width:frame.width,height:frame.height,sidebarsHidden:getComputedStyle(document.querySelector('aside')).display==='none'&&getComputedStyle(document.querySelector('.paper-column')).display==='none',headerHidden:getComputedStyle(document.querySelector('header')).display==='none'};})()")
                    if not focused['sidebarsHidden'] or not focused['headerHidden'] or focused['width']<=normal['width'] or focused['height']<=normal['height']:
                        raise RuntimeError('专注阅读未扩大PDF：'+str(focused))
                    api._window.evaluate_js("document.querySelector('.focus-reading-toggle').click();showPage('import');true")
                    if not api._window.evaluate_js("document.querySelector('#exportJSON').getBoundingClientRect().width>0"):
                        raise RuntimeError('导出按钮不可见')
                    result['reading_layout']={'normal':normal,'focused':focused,'export_visible':True}
                    navigation_checks={}
                    for page in ['import','ontology','settings']:
                        api._window.evaluate_js("showPage('"+page+"');const testSpacer=document.createElement('div');testSpacer.id='navigationScrollTest';testSpacer.style.height='1800px';document.getElementById('"+page+"').append(testSpacer);window.scrollTo(0,900);true")
                        time.sleep(.15)
                        navigation=api._window.evaluate_js("({top:document.querySelector('header').getBoundingClientRect().top,scroll:window.scrollY,position:getComputedStyle(document.querySelector('header')).position})")
                        if abs(navigation['top'])>2 or navigation['scroll']<500 or navigation['position']!='sticky':
                            raise RuntimeError('页面导航没有固定：'+page+str(navigation))
                        navigation_checks[page]=navigation
                        api._window.evaluate_js("document.querySelector('#navigationScrollTest').remove();window.scrollTo(0,0);true")
                    api._window.evaluate_js("showPage('ontology');document.querySelector('#labelForm').closest('details').open=true;true")
                    label_layout=api._window.evaluate_js("(()=>{const add=document.querySelector('#labelForm').closest('details'),list=document.querySelector('#ontologyList'),suggestions=document.querySelector('#labelSuggestions');return {formHeight:add.getBoundingClientRect().height,managerFollowsForm:add.nextElementSibling.id==='labelManagementHeading'&&document.querySelector('#labelManagementHeading').nextElementSibling===list,suggestionsAfterManager:list.nextElementSibling===suggestions};})()")
                    if label_layout['formHeight']>250 or not label_layout['managerFollowsForm'] or not label_layout['suggestionsAfterManager']:
                        raise RuntimeError('标签管理布局不符合要求：'+str(label_layout))
                    api._window.evaluate_js("document.querySelector('#labelForm').closest('details').open=false;showPage('library');window.scrollTo(0,0);true")
                    if api._window.evaluate_js("getComputedStyle(document.querySelector('header')).position==='sticky'"):
                        raise RuntimeError('文献库错误启用了页面导航固定')
                    result['content_navigation']={'pages':navigation_checks,'label_layout':label_layout}
                    api._window.evaluate_js("showPage('library');const spacer=document.createElement('div');spacer.id='listScrollTest';spacer.style.height='1800px';document.querySelector('.paper-column').append(spacer);document.querySelector('.paper-column').scrollTop=500;true")
                    sticky=api._window.evaluate_js("(()=>{const column=document.querySelector('.paper-column').getBoundingClientRect(),title=document.querySelector('.paper-column>.section-title').getBoundingClientRect();return {height:title.height,topDifference:Math.abs(title.top-column.top)};})()")
                    if sticky['height']>40 or sticky['topDifference']>2:
                        raise RuntimeError('文献数量标题栏没有固定或过高：'+str(sticky))
                    for label_id in ['control','game_theory']:
                        api._window.evaluate_js("document.querySelector('.paper-column').scrollTop=500;document.querySelector('#filters input[value=" + label_id + "]').click();true")
                        deadline=time.monotonic()+10
                        while time.monotonic()<deadline:
                            if api._window.evaluate_js("document.querySelector('.paper-column').scrollTop===0"):
                                break
                            time.sleep(.1)
                        if not api._window.evaluate_js("document.querySelector('.paper-column').scrollTop===0"):
                            raise RuntimeError('筛选后文献列表没有回顶')
                    api._window.evaluate_js("document.querySelector('#listScrollTest').remove();document.querySelector('#manageTagsLink').click();document.querySelector('[data-tag=control][data-op=rename]').click();true")
                    if not api._window.evaluate_js("document.querySelector('#renameLabelDialog').open"):
                        raise RuntimeError('重命名标签窗口不可用')
                    api._window.evaluate_js("document.querySelector('#renameLabelName').value='UI标签重命名';document.querySelector('#renameLabelForm').requestSubmit();true")
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        if api._window.evaluate_js("state.ontology.find(label=>label.id==='control')?.name==='UI标签重命名'"):
                            break
                        time.sleep(.1)
                    if not api._window.evaluate_js("state.ontology.find(label=>label.id==='control')?.name==='UI标签重命名'"):
                        raise RuntimeError('重命名没有保存')
                    api._window.evaluate_js("document.querySelector('[data-tag=control][data-op=delete]').click();true")
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        kept=api._window.evaluate_js("!state.ontology.find(label=>label.id==='control')?.active&&state.detail.tags.some(tag=>tag.label_id==='game_theory')&&!state.detail.tags.some(tag=>tag.label_id==='control')")
                        if kept:
                            break
                        time.sleep(.1)
                    if not kept:
                        raise RuntimeError('删除标签后其他归属没有保留')
                    api._window.evaluate_js("document.querySelector('[data-tag=control][data-op=restore]').click();true")
                    result['label_management']={'compact_sticky_header':sticky,'multiple_filters_return_to_top':True,'rename_dialog_saved':True,'delete_preserves_other_memberships':True}


                if tray:
                    if not tray.ready.wait(10) or tray.error:
                        raise RuntimeError('托盘初始化失败：'+str(tray.error))
                    tray.invoke(lambda: api._window.native.Close())
                    hidden = not api._window.native.Visible
                    with urllib.request.urlopen(url+'/api/settings', timeout=5) as response:
                        background_alive = response.status == 200
                    if not hidden or not tray.icon.Visible or not background_alive:
                        raise RuntimeError('关闭后没有保持托盘和后台服务')
                    from System import Array, Object
                    from System.Reflection import BindingFlags
                    from System.Windows.Forms import MouseButtons, MouseEventArgs
                    def click_tray(button):
                        method = tray.icon.GetType().GetMethod('OnMouseClick', BindingFlags.Instance | BindingFlags.NonPublic)
                        method.Invoke(tray.icon, Array[Object]([MouseEventArgs(button, 1, 0, 0, 0)]))
                    tray.invoke(lambda: click_tray(MouseButtons.Right))
                    if api._window.native.Visible:
                        raise RuntimeError('右键托盘不应恢复窗口')
                    tray.invoke(lambda: click_tray(MouseButtons.Left))
                    if not api._window.native.Visible:
                        raise RuntimeError('单击托盘未恢复窗口')
                    tray.invoke(lambda: api._window.native.Close())
                    from backend.database import DATA_ROOT
                    from desktop_tray import restore_existing_window
                    if not restore_existing_window(DATA_ROOT):
                        raise RuntimeError('重复启动无法唤回窗口')
                    deadline = time.monotonic()+3
                    while not api._window.native.Visible and time.monotonic()<deadline:
                        time.sleep(.05)
                    if not api._window.native.Visible:
                        raise RuntimeError('重复启动没有显示窗口')
                    tray.invoke(lambda: api._window.native.Close())
                    tray.invoke(lambda: tray.open_item.PerformClick())
                    if not api._window.native.Visible:
                        raise RuntimeError('托盘菜单未恢复窗口')
                    result['tray']={'registered':True,'close_hides_window':hidden,'background_alive':background_alive,'single_left_click_restores':True,'right_click_keeps_hidden':True,'relaunch_restores':True,'menu_restores':True,'exit_menu':True}
                target = Path(os.environ.get('LITERATURE_SMOKE_REPORT', 'desktop-smoke.json'))
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as exc:
                check_errors.append(exc)
            finally:
                if tray and tray.icon:
                    tray.invoke(lambda: tray.exit_item.PerformClick())
                else:
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
                from backend.database import DATA_ROOT
                from desktop_tray import restore_existing_window
                if restore_existing_window(DATA_ROOT):
                    sys.exit(0)
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, str(exception), '垃圾桶', 64)
            sys.exit(1)
        from backend.database import DATA_ROOT
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        (DATA_ROOT / 'desktop-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        if not any(flag in sys.argv for flag in ('--smoke-test', '--gui-smoke-test', '--validation-server')):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f'启动失败。请查看 {DATA_ROOT / "desktop-error.log"}\nWin11 需安装 Microsoft Edge WebView2 Runtime。', '垃圾桶', 16)
        sys.exit(1)
