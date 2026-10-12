"""Check trusted GitHub CI for an exact commit; never invokes hosting APIs."""
import json,os,re,urllib.request
repo=os.environ['GITHUB_REPOSITORY'];sha=os.environ['RELEASE_SHA']
if not re.fullmatch('[0-9a-f]{40}',sha):raise SystemExit('Full SHA required')
headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'}
for filename in ('ci.yml','container-validation.yml'):
    url=f'https://api.github.com/repos/{repo}/actions/workflows/{filename}/runs?head_sha={sha}&per_page=100'
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=30) as r:runs=json.load(r)['workflow_runs']
    runs=[r for r in runs if r.get('head_repository',{}).get('full_name')==repo and r.get('head_sha')==sha and r.get('event') in ('push','workflow_dispatch')]
    if not runs or max(runs,key=lambda r:r['run_number']).get('conclusion')!='success':raise SystemExit(filename+': exact-commit trusted CI is not green')
print('Exact-commit unit and container CI gates passed')
