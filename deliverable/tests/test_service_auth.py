from fastapi.testclient import TestClient
import pytest
import main
from test_api import FakePredictor, RESPONSE

KEY = 'test-only-edupredict-service-key-000'

@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setenv('EDUPREDICT_SERVICE_KEY', KEY)
    monkeypatch.setattr(main, 'predictor', FakePredictor())
    calls = []
    monkeypatch.setattr(main, 'build_student_prediction_request', lambda **kw: (calls.append(kw) or (1, kw)))
    monkeypatch.setattr(main, 'save_prediction', lambda *args: calls.append(('save', args)))
    return TestClient(main.app), calls

@pytest.mark.parametrize('method,path', [
    ('GET','/students/123/prediction'),('POST','/students/123/prediction'),
    ('POST','/students/123/scenario-prediction'),('POST','/predict'),('POST','/predict/batch'),
])
def test_anonymous_and_forged_actor_never_reach_data(protected, method, path):
    client, calls = protected
    for headers in [{}, {'X-EduFusion-Role':'admin'}, {'X-Service-Key':'wrong','X-EduFusion-Role':'student','X-EduFusion-Student-Id':'123'}]:
        response = client.request(method,path,headers=headers,json={})
        assert response.status_code == 401
    assert calls == []

def test_missing_key_configuration_fails_closed(protected,monkeypatch):
    client,calls=protected
    monkeypatch.delenv('EDUPREDICT_SERVICE_KEY')
    assert client.get('/students/123/prediction').status_code == 503
    assert calls == []

@pytest.mark.parametrize('method', ['GET','POST'])
@pytest.mark.parametrize('role,student', [('student','456'),('advisor','123'),('student',''),('', '123')])
def test_foreign_or_unscoped_actor_is_denied(protected,method,role,student):
    client,calls=protected
    response=client.request(method,'/students/123/prediction',headers={'X-Service-Key':KEY,'X-EduFusion-Role':role,'X-EduFusion-Student-Id':student})
    assert response.status_code == 403
    assert calls == []

def test_get_computes_without_saving_and_post_explicitly_persists(protected):
    client,calls=protected
    headers={'X-Service-Key':KEY,'X-EduFusion-Role':'student','X-EduFusion-Student-Id':'123'}
    get=client.get('/students/123/prediction?code_module=BBB&threshold=0.41',headers=headers)
    assert get.status_code==200
    assert get.json()==RESPONSE.model_dump(mode='json')
    assert len(calls)==1 and calls[0]['id_student']==123
    post=client.post('/students/123/prediction?code_module=BBB&threshold=0.41',headers=headers)
    assert post.status_code==200 and post.json()==get.json()
    assert len([x for x in calls if isinstance(x,tuple) and x[0]=='save'])==1

def test_foreign_scenario_is_denied_before_evidence_load(protected):
    from test_scenario import scenario
    client,calls=protected
    response=client.post('/students/456/scenario-prediction',json=scenario().model_dump(),headers={
        'X-Service-Key':KEY,'X-EduFusion-Role':'student','X-EduFusion-Student-Id':'123'})
    assert response.status_code==403 and calls==[]
