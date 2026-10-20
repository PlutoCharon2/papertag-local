import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import httpx
import pymupdf
import pytest
from backend import api_service as service, auto_analysis_service as ai
from backend.database import connect
from backend.import_service import import_file
from test_api_providers import client, body


@pytest.fixture
def pool(client,tmp_path,monkeypatch):
    monkeypatch.setattr(ai,'_stop',threading.Event())
    keys=[{'id':f'key{i}','value':f'synthetic-only-key-{i}','enabled':True} for i in range(3)]
    assert client.post('/api/ai/provider',json={**body(),'api_key':'','keys':keys}).status_code==200
    monkeypatch.setitem(service._key_cursor,'qwen',0)
    papers={}
    for i in range(3):
        path=tmp_path/f'paper{i}.pdf'
        with pymupdf.open() as doc:
            doc.new_page().insert_text((40,50),f'Synthetic paper {i} with evidence.')
            doc.save(path)
        with connect() as c:
            _,pid=import_file(c,path)
            paper=dict(c.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone())
        papers[ai.enqueue(pid)]=paper
    yield client,keys,papers


def output(paper,version,new_labels=True):
    data={'paper_id':paper['id'],'document_hash':paper['file_hash'],'ontology_version':version,'schema_version':2,
          'title':f"Paper {paper['id']}",'authors':[],'year':None,'doi':'','paper_type':'unknown','summary':'Synthetic',
          'tags':[],'claims':[],'suggestions':[],'new_labels':[]}
    if new_labels:
        key=f"new_test_{paper['id']}"
        data['tags']=[{'label_id':key,'evidence':[{'page':1,'quote':'Synthetic paper'}]}]
        data['new_labels']=[{'key':key,'dimension':'application','name':f"Synthetic topic {paper['id']}",'definition':'Synthetic test only'}]
    return data


def fake_transport(papers,started,release,calls,new_labels=True):
    guard=threading.Lock()
    def fake(workspace,images,prompt,*args):
        job=int(workspace.name)
        version=json.loads(prompt.split('必须保持的标识字段：\n')[-1])['ontology_version']
        with guard:
            calls.append((job,service.credentials()[2],version))
            if len(calls)==started[0]: started[1].set()
        assert release.wait(10)
        raw=json.dumps(output(papers[job],version,new_labels))
        (workspace/'response.json').write_text(raw,encoding='utf-8')
        return raw
    return fake


def test_three_keys_overlap_and_merge_new_ontology_without_duplicate_jobs(pool,monkeypatch):
    client,keys,papers=pool
    calls=[];ready=threading.Event();release=threading.Event()
    monkeypatch.setattr(service,'infer',fake_transport(papers,(3,ready),release,calls))
    assert client.get('/api/ai/status').json()['config']['concurrency']==3
    first=next(iter(papers.values()))['id']
    client.post(f'/api/papers/{first}/decision',json={'label_id':'control','decision':'manual'})
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures=[executor.submit(ai.analyze_one,j) for j in papers]
        try:
            assert ready.wait(8), 'three requests did not overlap'
            executor.submit(ai.analyze_one,next(iter(papers))).result(timeout=2)
            assert not ai._execution_lock.acquire(blocking=False)
        finally:
            release.set()
        for future in futures: future.result(timeout=10)
    assert len(calls)==3 and len({c[1] for c in calls})==3
    assert {c[2] for c in calls}=={1}
    assert all(j['status']=='completed' for j in client.get('/api/ai/jobs').json())
    assert any(t['label_id']=='control' for t in client.get(f'/api/papers/{first}').json()['tags'])
    assert len([l for l in client.get('/api/ontology').json()['labels'] if l['name'].startswith('Synthetic topic')])==3


def test_one_enabled_key_has_one_slot(pool,monkeypatch):
    client,keys,papers=pool
    keys[1]['enabled']=keys[2]['enabled']=False
    client.post('/api/ai/provider',json={**body(),'api_key':'','keys':keys})
    assert client.get('/api/ai/status').json()['config']['concurrency']==1
    calls=[];ready=threading.Event();release=threading.Event()
    monkeypatch.setattr(service,'infer',fake_transport(papers,(1,ready),release,calls,False))
    ids=list(papers)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first=executor.submit(ai.analyze_one,ids[0])
        try:
            assert ready.wait(5)
            executor.submit(ai.analyze_one,ids[1]).result(timeout=2)
            assert len(calls)==1
        finally: release.set()
        first.result(timeout=10)
    assert next(j for j in client.get('/api/ai/jobs').json() if j['id']==ids[1])['status']=='queued'
    ai.analyze_one(ids[1])
    assert [c[1] for c in calls]==[keys[0]['value'],keys[0]['value']]


def test_pause_all_blocks_commits_and_resume_reuses_parallel_responses(pool,monkeypatch):
    client,keys,papers=pool
    calls=[];ready=threading.Event();release=threading.Event()
    monkeypatch.setattr(service,'infer',fake_transport(papers,(3,ready),release,calls))
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures=[executor.submit(ai.analyze_one,j) for j in papers]
        try:
            assert ready.wait(8)
            assert client.post('/api/ai/provider',json={**body(),'api_key':'','keys':keys}).status_code==400
            assert client.post('/api/ai/pause-all',json={}).json()['paused']==3
            assert client.post('/api/ai/resume-all',json={}).status_code==409
        finally: release.set()
        for f in futures: f.result(timeout=10)
    assert all(j['status']=='paused' for j in client.get('/api/ai/jobs').json())
    with connect() as c: assert c.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0
    assert client.post('/api/ai/resume-all',json={}).json()['resumed']==3
    for j in papers: ai.analyze_one(j)
    assert len(calls)==3
    assert all(j['status']=='completed' for j in client.get('/api/ai/jobs').json())


def test_bad_key_isolated_and_explicitly_rejected_request_can_requeue(pool,monkeypatch):
    client,keys,papers=pool
    client.post('/api/ai/provider',json={**body(),'api_key':'','keys':keys[:2]})
    monkeypatch.setattr(service,'choose_idle_key',lambda rows:rows[0])
    requests=[]
    def handler(request):
        key=request.headers['authorization'].split(' ',1)[1]
        requests.append(key)
        if key==keys[0]['value']: return httpx.Response(401)
        prompt=json.loads(request.content)['messages'][1]['content'][0]['text']
        identity=json.loads(prompt.split('必须保持的标识字段：\n')[-1])
        paper=next(p for p in papers.values() if p['id']==identity['paper_id'])
        event={'choices':[{'delta':{'content':json.dumps(output(paper,identity['ontology_version'],False))},'finish_reason':'stop'}]}
        return httpx.Response(200,text='data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n')
    original=httpx.Client
    monkeypatch.setattr(service.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    ids=list(papers)
    ai.analyze_one(ids[0]);ai.analyze_one(ids[1])
    jobs={j['id']:j for j in client.get('/api/ai/jobs').json()}
    assert jobs[ids[0]]['status']=='queued' and jobs[ids[1]]['status']=='completed'
    assert requests==[keys[0]['value'],keys[1]['value']]
    assert client.get('/api/ai/status').json()['config']['usable_keys']==1
    assert client.get('/api/ai/status').json()['config']['enabled']
    ai.analyze_one(ids[0])
    assert requests==[keys[0]['value'],keys[1]['value'],keys[1]['value']]
    assert next(j for j in client.get('/api/ai/jobs').json() if j['id']==ids[0])['status']=='completed'


def test_keys_reveal_only_explicit_local_request_and_duplicates_rejected(pool):
    client,keys,_=pool
    assert client.post('/api/ai/provider/keys',json={'provider':'qwen'}).status_code==403
    response=client.post('/api/ai/provider/keys',json={'provider':'qwen'},headers={'X-PaperTag-Key-View':'1'})
    assert response.headers['cache-control']=='no-store'
    assert response.json()['keys']==keys
    assert 'synthetic-only-key' not in json.dumps(client.get('/api/ai/providers').json())
    assert client.post('/api/ai/provider/keys',json={'provider':'qwen'},headers={'X-PaperTag-Key-View':'1','Origin':'https://example.org'}).status_code==403
    assert client.post('/api/ai/provider',json={**body(),'api_key':'','keys':[keys[0],{**keys[0],'id':'other'}]}).status_code==400
    assert client.get('/api/ai/providers').json()['profiles']['qwen']['key_count']==3


def test_legacy_single_key_migrates_without_loss(client):
    client.post('/api/ai/provider',json=body())
    with connect() as c:
        item=service.profile(c,'qwen');item.pop('keys')
        c.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(item),'api_profile_qwen'))
    assert service.reveal_keys('qwen')[0]['value']=='test-only-secret'
    assert client.get('/api/ai/status').json()['config']['concurrency']==1
    new=service.reveal_keys('qwen')+[{'id':'second','value':'second-test-key','enabled':True}]
    assert client.post('/api/ai/provider',json={**body(),'api_key':'','keys':new}).status_code==200
    assert service.reveal_keys('qwen')==new


def test_scheduler_dispatches_one_worker_per_key(pool,monkeypatch):
    client,_,papers=pool
    calls=[];ready=threading.Event();release=threading.Event()
    monkeypatch.setattr(service,'infer',fake_transport(papers,(3,ready),release,calls))
    worker=threading.Thread(target=ai._loop)
    worker.start()
    try:
        assert ready.wait(8)
        release.set()
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if all(j['status']=='completed' for j in client.get('/api/ai/jobs').json()): break
            time.sleep(.05)
        assert all(j['status']=='completed' for j in client.get('/api/ai/jobs').json())
        assert len(calls)==3
    finally:
        release.set();ai._stop.set();worker.join(timeout=10)
    assert not worker.is_alive()


def test_parallel_rebase_does_not_accept_wrong_prompt_version(pool,monkeypatch):
    client,_,papers=pool
    def fake(workspace,*args):
        return json.dumps(output(papers[int(workspace.name)],999))
    monkeypatch.setattr(service,'infer',fake)
    ai.analyze_one(next(iter(papers)))
    with connect() as c: assert c.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0
    assert any(j['status']=='failed' for j in client.get('/api/ai/jobs').json())


def test_fast_key_takes_next_paper_before_slow_key_finishes(pool,monkeypatch):
    client,keys,papers=pool
    client.post('/api/ai/provider',json={**body(),'api_key':'','keys':keys[:2]})
    ids=list(papers);slow=threading.Event();third=threading.Event();used={}
    def fake(workspace,images,prompt,*args):
        job=int(workspace.name);used[job]=service.credentials()[2]
        if job==ids[0]: assert slow.wait(10)
        if job==ids[2]: third.set()
        version=json.loads(prompt.split('必须保持的标识字段：\n')[-1])['ontology_version']
        return json.dumps(output(papers[job],version,False))
    monkeypatch.setattr(service,'infer',fake)
    worker=threading.Thread(target=ai._loop);worker.start()
    try:
        assert third.wait(8),'fast key did not refill while slow key was occupied'
        assert not slow.is_set()
        assert used[ids[1]]==used[ids[2]] and used[ids[0]]!=used[ids[2]]
        slow.set()
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if all(j['status']=='completed' for j in client.get('/api/ai/jobs').json()): break
            time.sleep(.05)
        assert all(j['status']=='completed' for j in client.get('/api/ai/jobs').json())
    finally:
        slow.set();ai._stop.set();worker.join(timeout=10)
    assert not worker.is_alive()


def test_rate_limited_key_waits_without_failing_or_repeating_before_cooldown(pool,monkeypatch):
    client,keys,papers=pool
    client.post('/api/ai/provider',json={**body(),'api_key':'','keys':keys[:1]})
    requests=[]
    def handler(request):
        requests.append(1)
        if len(requests)==1:return httpx.Response(429,headers={'Retry-After':'600'})
        prompt=json.loads(request.content)['messages'][1]['content'][0]['text']
        identity=json.loads(prompt.split('必须保持的标识字段：\n')[-1])
        paper=next(p for p in papers.values() if p['id']==identity['paper_id'])
        event={'choices':[{'delta':{'content':json.dumps(output(paper,identity['ontology_version'],False))},'finish_reason':'stop'}]}
        return httpx.Response(200,text='data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n')
    original=httpx.Client
    monkeypatch.setattr(service.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    job=next(iter(papers))
    ai.analyze_one(job)
    config=client.get('/api/ai/status').json()['config']
    assert config['enabled'] and config['key_pool']['cooling']==1
    ai.analyze_one(job)
    assert len(requests)==1
    assert next(j for j in client.get('/api/ai/jobs').json() if j['id']==job)['status']=='queued'
    monkeypatch.setitem(service._key_cooldowns,('qwen','key0'),time.monotonic()-1)
    ai.analyze_one(job)
    assert len(requests)==2
    assert next(j for j in client.get('/api/ai/jobs').json() if j['id']==job)['status']=='completed'
