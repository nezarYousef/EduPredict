"""Wait only for named disposable CI containers; never prints runtime configuration."""
import json, subprocess, sys, time
for name in sys.argv[1:]:
    if not name.endswith('-fixture'):
        raise SystemExit('Only fixture containers are accepted')
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',name]))
        if state.get('Health',{}).get('Status')=='healthy':
            print(name+': healthy')
            break
        if not state.get('Running'):
            raise SystemExit(name+': process exited')
        time.sleep(2)
    else:
        raise SystemExit(name+': health deadline exceeded')
