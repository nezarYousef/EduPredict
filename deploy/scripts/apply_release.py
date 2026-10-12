"""Dormant, explicitly authorized single-service Dokploy apply adapter.
Default is a local dry run. No GET requests or environment-value retrieval.
"""
import argparse,json,os,re,time,urllib.request,urllib.error
from pathlib import Path
import yaml


def prepare(base, release, target):
    if target.get('source_type')!='raw' or target.get('environment') not in ('staging','production'):
        raise ValueError('Only an approved raw Compose target is supported')
    if not re.fullmatch(r'https://[a-zA-Z0-9.-]+(?::[0-9]+)?',target.get('dokploy_url','')):
        raise ValueError('Exact HTTPS Dokploy origin required')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,}',target.get('compose_id','')) or '__SET_' in target['compose_id']:
        raise ValueError('Reviewed target ID required')
    if list(base.get('services',{})) != [target.get('service')] or set(release)!=set(base):
        raise ValueError('Single approved service required')
    name=target['service']
    if name in {'postgres','mongo','qdrant'} or base['services'][name].get('profiles'):
        raise ValueError('Store/worker deployment is not supported by this adapter')
    image=release['services'][name].get('image','')
    if not re.fullmatch(r'[a-z0-9][a-z0-9./:_-]+@sha256:[0-9a-f]{64}',image):
        raise ValueError('Immutable image required')
    expected=json.loads(json.dumps(base));expected['services'][name]['image']=image
    if expected!=release:
        raise ValueError('Only the selected image may differ; preserve state, network and environment bindings')
    return {'composeId':target['compose_id'],'composeFile':yaml.safe_dump(release,sort_keys=False)}


def post(origin, method, payload, key):
    request=urllib.request.Request(origin+'/api/'+method,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-api-key':key},method='POST')
    # Do not print/read a returned service object: it may include configuration.
    with urllib.request.urlopen(request,timeout=30) as response:
        if response.status not in (200,201,202,204):raise RuntimeError('Control-plane operation rejected')


def main():
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--release',type=Path,required=True);p.add_argument('--target',type=Path,required=True);p.add_argument('--execute',action='store_true');p.add_argument('--approval-id',default='');a=p.parse_args()
    target=json.loads(a.target.read_text());payload=prepare(yaml.safe_load(a.base.read_text()),yaml.safe_load(a.release.read_text()),target)
    if not a.execute:
        print(json.dumps({'mode':'DRY_RUN','environment':target['environment'],'service':target['service'],'operations':['compose.update(composeFile only)','compose.deploy'],'health_verification':'REQUIRED AFTERWARD'}));return
    if os.environ.get('DOKPLOY_APPLY_APPROVED')!='true' or not a.approval_id.strip():raise ValueError('Explicit approval flag and recorded approval ID required')
    key=os.environ.get('DOKPLOY_API_KEY','')
    if not key:raise ValueError('Scoped control-plane credential required')
    post(target['dokploy_url'],'compose.update',payload,key)
    post(target['dokploy_url'],'compose.deploy',{'composeId':target['compose_id']},key)
    print('Deployment requested; NOT verified. Run restricted health/contract checks and record the outcome before admitting traffic.')

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError) as error:raise SystemExit(str(error))
    except Exception:raise SystemExit('Release operation failed; inspect sanitized control-plane status. Do not print request headers or response configuration.')
