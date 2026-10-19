"""Recreate isolated public dependencies and pinned official source checkouts."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[2]
PINS={
 'RankingShap':('https://github.com/MariaHeuss/RankingShap.git','36e45975f34ee167261af56c69521d55c998b282'),
 'ShaRP':('https://github.com/DataResponsibly/ShaRP.git','6543226b7c4952aab61a15a977964344cabbf929'),
 'Shapley-Flow':('https://github.com/nathanwang000/Shapley-Flow.git','0d9063f81759d4317de6c33d7782e5ec4a4cde85')}

def main():
    env=ROOT/'local/q1-venv'
    if not env.exists():venv.EnvBuilder(with_pip=True).create(env)
    python=env/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'experiments/q1_pilot/requirements.lock.txt')],check=True)
    for name,(url,commit) in PINS.items():
        target=ROOT/'local/q1-upstream'/name
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['git','clone',url,str(target)],check=True)
            subprocess.run(['git','-C',str(target),'checkout','--detach',commit],check=True)
        head=subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
        dirty=subprocess.check_output(['git','-C',str(target),'status','--porcelain','--untracked-files=no'],text=True).strip()
        if head!=commit or dirty:raise RuntimeError('Existing checkout differs; refusing to reset '+name)
    print('Q1 isolated dependencies and official pins verified')

if __name__=='__main__':main()
