"""Isolated GUI checks, activated only by the explicit smoke-test environment."""
import json
import time
import urllib.request


def check_interactions(window):
    def wait(expression):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if window.evaluate_js('Boolean('+expression+')'): return
            time.sleep(.1)
        raise RuntimeError('Interaction check failed: '+expression)
    window.evaluate_js("document.querySelector('#apiConfigDialog').close();showPage('import');loadAIJobs();true")
    wait("document.querySelector('[data-open-paper]')")
    window.evaluate_js("document.querySelector('#search').value='will hide paper';document.querySelector('[data-open-paper]').click();true")
    wait("state.page==='library'&&state.detail&&document.querySelector('.paper-card.selected')&&document.querySelector('#search').value===''")
    window.evaluate_js("document.querySelector('#openTagReview').click();true")
    sizes=window.evaluate_js("({label:parseFloat(getComputedStyle(document.querySelector('#tagReviewDialog .tag-review .chip')).fontSize),evidence:parseFloat(getComputedStyle(document.querySelector('#tagReviewDialog .tag-review summary')).fontSize),gray:getComputedStyle(document.querySelector('#tagReviewDialog .chip.ai')).color,background:getComputedStyle(document.querySelector('#tagReviewDialog .chip.ai')).backgroundColor,border:getComputedStyle(document.querySelector('#tagReviewDialog .chip.ai')).borderTopWidth})")
    assert sizes['label']>sizes['evidence'] and sizes['gray']=='rgb(101, 120, 135)' and sizes['background']=='rgba(0, 0, 0, 0)' and sizes['border']=='0px',sizes
    assert window.evaluate_js("getComputedStyle(document.querySelector('#tagReviewDialog .validation-issues li')).color")=='rgb(155, 112, 0)'
    window.evaluate_js("document.querySelector('#tagReviewDialog [data-decision=accepted]').click();true")
    wait("document.querySelector('#tagReviewDialog .chip.accepted')")
    assert window.evaluate_js("getComputedStyle(document.querySelector('#tagReviewDialog .chip.accepted')).color")=='rgb(22, 76, 145)'
    wait("document.querySelector('.paper-card .chip.accepted')")
    assert window.evaluate_js("getComputedStyle(document.querySelector('.paper-card .chip.accepted')).backgroundColor")=='rgb(255, 241, 188)'
    assert window.evaluate_js("getComputedStyle(document.querySelector('.paper-card .publication-year')).backgroundColor")=='rgb(237, 242, 246)'
    assert window.evaluate_js("getComputedStyle(document.querySelector('.paper-card .publication-venue')).backgroundColor")=='rgb(237, 242, 246)'
    window.evaluate_js("document.querySelector('#tagReviewDialog [data-decision=rejected]').click();true")
    wait("document.querySelector('#tagReviewDialog .chip.rejected')")
    assert window.evaluate_js("getComputedStyle(document.querySelector('#tagReviewDialog .chip.rejected')).color")=='rgb(161, 38, 38)'
    window.evaluate_js("document.querySelector('#tagReviewDialog [data-decision=reset]').click();true")
    wait("document.querySelector('#tagReviewDialog .chip.ai')")
    window.evaluate_js("document.querySelector('#tagReviewDialog').close();state.interactionSelected=state.selected;document.querySelector('#sameClaim').checked=true;document.querySelector('#search').value='no_such_synthetic_paper';document.querySelector('#search').dispatchEvent(new Event('input'));true")
    wait("state.papers.length===0")
    window.evaluate_js("document.querySelector('#sameClaim').checked=false;document.querySelector('#search').value='';document.querySelector('#search').dispatchEvent(new Event('input'));true")
    wait("state.papers.length>0&&document.querySelector('#sameClaim').checked&&state.selected===state.interactionSelected")
    window.evaluate_js("document.querySelector('#search').value='Synthetic';document.querySelector('#search').dispatchEvent(new Event('input'));true")
    wait("state.papers.length>0&&state.papers.every(p=>p.title.includes('Synthetic'))")
    window.evaluate_js("document.querySelector('#search').value='';document.querySelector('#search').dispatchEvent(new Event('input'));true")
    return {'task_navigation':True,'review_colors':{'unhandled':'gray','validation_failed':'yellow','accepted':'blue','rejected':'red'},'review_text_only':True,'card_tags_stay_yellow':True,'publication_chips_stay_gray':True,'label_larger_than_evidence':True,'live_search':True,'restore_filters_and_selection':True}


def check_keys_and_review(window,url):
    def wait_js(expression,message,seconds=15):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if window.evaluate_js('Boolean('+expression+')'): return
            time.sleep(.1)
        raise RuntimeError(message)
    def config():
        with urllib.request.urlopen(url+'/api/ai/status',timeout=5) as response:
            return json.load(response)['config']
    def save(expected):
        window.evaluate_js("document.querySelector('#apiProfileForm').requestSubmit();true")
        wait_js("!document.querySelector('#apiProfileForm button[type=submit]').disabled&&document.querySelector('#apiTestResult').textContent.startsWith('已保存。')",'密钥行保存失败')
        if config()['usable_keys']!=expected: raise RuntimeError('启用密钥数没有决定并行数')
    wait_js("document.querySelector('#apiKeyRows')&&!document.querySelector('#apiProfileForm button[type=submit]').disabled",'密钥行未就绪')
    window.evaluate_js("document.querySelector('#addAPIKey').click();document.querySelector('#addAPIKey').click();document.querySelectorAll('.api-key-input').forEach((el,i)=>el.value='synthetic-gui-only-key-'+i);true")
    save(3)
    window.evaluate_js("document.querySelector('#apiConfigDialog').close();openAPIConfiguration();true")
    wait_js("document.querySelectorAll('.api-key-input').length===3&&[...document.querySelectorAll('.api-key-input')].every(el=>el.value.length>0&&el.type==='password')",'已保存的密钥重新打开后为空')
    window.evaluate_js("document.querySelector('.api-key-row button').click();true")
    if not window.evaluate_js("document.querySelector('.api-key-input').type==='text'"): raise RuntimeError('密钥查看按钮无效')
    window.evaluate_js("document.querySelector('.api-key-row button').click();document.querySelector('#apiKeyRows').lastElementChild.lastElementChild.click();true")
    save(2)
    window.evaluate_js("document.querySelector('.api-key-enabled').checked=false;true")
    save(1)
    window.evaluate_js("document.querySelector('.api-key-enabled').checked=true;true")
    save(2)
    window.evaluate_js("document.querySelector('#apiConfigDialog').close();showPage('library');loadDetail(state.papers[0].id);true")
    wait_js("document.querySelector('#reviewClaims')&&document.querySelector('#pdfViewerFrame')?.contentWindow?.PDFViewerApplication?.pdfDocument",'合并审核或原文阅读器未就绪')
    window.evaluate_js("document.querySelector('#openTagReview').click();true")
    review=window.evaluate_js("({inside:!!document.querySelector('#tagReviewDialog #reviewClaims'),claims:document.querySelectorAll('#reviewClaims article').length,separateAbsent:!document.querySelector('#openClaims')&&!document.querySelector('#claimsDialog'),location:document.querySelector('#openOriginalLocation')?.textContent==='打开原文位置'&&!!window.pywebview.api.open_original_location})")
    if not all([review['inside'],review['claims']==1,review['separateAbsent'],review['location']]): raise RuntimeError('审核合并或原文位置入口错误')
    window.evaluate_js("document.querySelector('#reviewClaims [data-pdf-page=\"2\"]').click();true")
    wait_js("!document.querySelector('#tagReviewDialog').open&&document.querySelector('#pdfViewerFrame').contentWindow.PDFViewerApplication.page===2",'审核证据未定位到原文页')
    return {'saved_keys_filled':True,'masked_by_default':True,'reveal_toggle':True,'parallel_counts':[3,2,1,2],
            'merged_review':review,'evidence_page':2,'real_api_calls':False}
