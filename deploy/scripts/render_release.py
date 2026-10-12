"""Render a secret-free, one-service immutable release; never calls Dokploy."""
import argparse,json,re
from pathlib import Path
import yaml
p=argparse.ArgumentParser();p.add_argument('--compose',type=Path,required=True);p.add_argument('--service',required=True);p.add_argument('--image',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9./:_-]+@sha256:[0-9a-f]{64}',a.image):
    p.error('Use an immutable repository@sha256 digest')
doc=yaml.safe_load(a.compose.read_text())
if list(doc['services'])!=[a.service]:
    p.error('Exactly one reviewed service is required')
if a.service in {'postgres','mongo','qdrant'} or doc['services'][a.service].get('profiles'):
    p.error('Databases and processing workers require a separate authorized runbook')
doc['services'][a.service]['image']=a.image
a.output.write_text(yaml.safe_dump(doc,sort_keys=False))
print('Immutable single-service manifest prepared; no deployment performed')
