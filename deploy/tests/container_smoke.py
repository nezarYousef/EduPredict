"""Production process on loopback; synthetic key only, no academic writes or AI calls."""
import json,os,urllib.request,urllib.error
key=os.environ['EDUPREDICT_SERVICE_KEY']
def request(route,expected,headers=None,data=None):
    req=urllib.request.Request('http://127.0.0.1:8000'+route,data=data,headers=headers or {})
    try:
        with urllib.request.urlopen(req,timeout=5) as response:
            status=response.status;body=response.read()
    except urllib.error.HTTPError as error:
        status=error.code;body=error.read()
    assert status==expected,(route,status,expected)
    return json.loads(body)
health=request('/health',200)
assert health['model_loaded'] is True and health['feature_count']>0
request('/ready',200)
request('/students/123/prediction',401)
request('/students/123/prediction',401,{'X-Service-Key':'synthetic-wrong-key'})
request('/students/123/prediction',403,{'X-Service-Key':key,'X-EduFusion-Role':'student','X-EduFusion-Student-Id':'124'})
# Valid authentication reaches schema validation, never DB/student lookup.
request('/predict',422,{'X-Service-Key':key,'X-EduFusion-Role':'admin','Content-Type':'application/json'},b'{}')
print('PASS: production CMD, model health, PG18 readiness, service authentication and foreign-student rejection')
