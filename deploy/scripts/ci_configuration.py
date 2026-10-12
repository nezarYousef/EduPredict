"""Offline CI guards. Never load repository .env files or contact a deployment API."""
import argparse,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
import yaml

BRANCH='codex/dokploy-staging-preparation'

def validate(document):
    errors=[]
    for name,service in document.get('services',{}).items():
        if service.get('ports') or service.get('privileged') or service.get('network_mode')=='host':
            errors.append(name+': public/privileged runtime')
        if not service.get('mem_limit') or not service.get('cpus'):
            errors.append(name+': missing resource ceilings')
        if service.get('restart')!='unless-stopped':errors.append(name+': restart policy')
        if re.search(r'migrat|seed',json.dumps(service.get('command',[]))+json.dumps(service.get('entrypoint',[])),re.I):
            errors.append(name+': automatic migration/seed')
        for key,value in service.get('environment',{}).items():
            if re.search(r'PASSWORD|SECRET|SERVICE_KEY|GATEWAY_KEY|API_KEY|DATABASE_URL|MONGO_URI',key):
                if key=='ADMIN_BOOTSTRAP_PASSWORD' and value=='':continue
                if not isinstance(value,str) or not value.startswith(chr(36)+'{'):errors.append(name+': literal credential '+key)
        for mount in service.get('volumes',[]):
            source=mount.split(':')[0] if isinstance(mount,str) else mount.get('source')
            if source not in document.get('volumes',{}):errors.append(name+': unreviewed state bind')
    for name,value in document.get('volumes',{}).items():
        if value.get('external') is not True or not value.get('name'):errors.append(name+': replacement empty volume risk')
    for name,value in document.get('networks',{}).items():
        if value.get('external') is not True:errors.append(name+': implicit network')
    return errors

def workflow_errors(text):
    doc=yaml.load(text,Loader=yaml.BaseLoader)
    errors=[]
    if doc.get('permissions')!={'contents':'read'}:errors.append('Unexpected workflow permissions')
    events=doc.get('on',{})
    if 'pull_request_target' in events or 'schedule' in events or 'workflow_run' in events:errors.append('Unsafe trigger')
    if BRANCH not in events.get('push',{}).get('branches',[]):errors.append('Review branch must run on first push')
    if re.search(r'secrets\.|packages:\s*write|docker\s+push|compose\.deploy|compose\.update|dokploy-release|apply_release\.py|registry-password|deploy-hook',text,re.I):errors.append('Deployment/secret operation in build-only CI')
    for job in doc.get('jobs',{}).values():
        if job.get('runs-on')!='ubuntu-24.04':errors.append('Expected Ubuntu24.04 runner')
        if job.get('environment'):errors.append('No hosting environment in validation CI')
    return errors

def check(root,compose):
    files=sorted((root/'deploy/dokploy').glob('*.compose.yaml'))
    if not files:raise ValueError('No manifests found')
    workflow=(root/'.github/workflows/container-validation.yml').read_text()
    failures=workflow_errors(workflow)
    for file in files:
        text=file.read_text();doc=yaml.safe_load(text)
        failures.extend(file.name+': '+e for e in validate(doc))
        required=set(re.findall(r'\$\{([A-Z0-9_]+)',text))
        template=file.with_name(file.name.replace('.compose.yaml','.env.example')).read_text()
        lines=[x for x in template.splitlines() if x and not x.startswith('#')]
        if {x.split('=',1)[0] for x in lines}!=required or any(not re.fullmatch(r'[A-Z0-9_]+=__SET_[A-Z0-9_]+__',x) for x in lines):failures.append(file.name+': invalid template')
        # Copy only this manifest and fresh synthetic values. Never resolve a real .env.
        values={key:('example.invalid/fixture@sha256:'+'a'*64 if key.endswith('_IMAGE') else 'fixture-value') for key in required}
        with tempfile.TemporaryDirectory(prefix='edufusion-config-fixture-') as folder:
            folder=Path(folder);(folder/'compose.yaml').write_text(text)
            (folder/'.env').write_text(''.join(key+'='+value+'\n' for key,value in sorted(values.items())))
            env={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','HOME'}}
            result=subprocess.run(compose+['--project-name','edufusion-config-fixture','--env-file',str(folder/'.env'),'--profile','*','-f',str(folder/'compose.yaml'),'config','--quiet'],env=env,capture_output=True,text=True,timeout=30)
            if result.returncode:failures.append(file.name+': Compose rejected synthetic configuration: '+result.stderr.strip())
    if failures:raise ValueError('\n'.join(failures))
    print(json.dumps({'manifests':len(files),'status':'PASS','scope':'offline synthetic Compose; no runtime readiness claim'}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--compose-bin');args=parser.parse_args()
    check(args.root,[args.compose_bin] if args.compose_bin else ['docker','compose'])
