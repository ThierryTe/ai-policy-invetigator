#!/usr/bin/env python3
"""Qualify an already authorized, already built immutable image; never build/pull.

This test deliberately does not set DJL_DEFAULT_ENGINE or DJL_OFFLINE: the image
must supply the proposed defaults itself. Each JVM gets new tmpfs scratch and no
network except loopback to a disposable synthetic startup fixture in context mode.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MODELS={
    'model.onnx':(90405214,'6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452'),
    'tokenizer.json':(466247,'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037')}
REVISION=':'.join(v[1] for v in MODELS.values())
NATIVES=[('tokenizers-0.36.0.jar','native/lib/linux-x86_64/cpu/libtokenizers.so'),
         ('onnxruntime-1.21.1.jar','ai/onnxruntime/native/linux-x64/libonnxruntime.so'),
         ('onnxruntime-1.21.1.jar','ai/onnxruntime/native/linux-x64/libonnxruntime4j_jni.so')]


def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True,help='Immutable corrected image ID/digest already in local Docker')
    parser.add_argument('--expected-jar-sha256',required=True)
    parser.add_argument('--expected-config-sha256',required=True)
    parser.add_argument('--baseline-jar',required=True,type=Path,help='Preserved failed JAR, sha256 bee5e753...0773b5')
    parser.add_argument('--models',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path,help='New evidence directory; never overwritten')
    parser.add_argument('--docker-context',default='desktop-linux')
    parser.add_argument('--database-image',default='sha256:a132765ec351c65111b5b675928a3a0515a466a40f97277329db8b8209ad8bc9')
    args=parser.parse_args()
    for digest in [args.expected_jar_sha256,args.expected_config_sha256]:
        if not re.fullmatch('[0-9a-f]{64}',digest): parser.error('Exact SHA-256 required')
    for image in [args.image,args.database_image]:
        if not re.fullmatch(r'(?:[a-z0-9./:_-]+@)?sha256:[0-9a-f]{64}',image): parser.error('Immutable image digest required')
    output=args.output.resolve()
    if output.is_relative_to(ROOT): parser.error('Keep evidence outside the repository')
    output.mkdir(exist_ok=False)
    docker=['docker','--context',args.docker_context]
    owned=[]
    prefix='embedding-regression-'+uuid.uuid4().hex[:12]
    report={'scope':'Exact corrected image qualification; synthetic offline inference and startup only; no deployment authorization',
            'image':args.image,'expectedJarSha256':args.expected_jar_sha256,'expectedConfigSha256':args.expected_config_sha256,
            'commands':[],'gates':{},'models':MODELS,'productionWorkersEnabled':False,'flywayEnabled':False}

    def run(argv,*,stdin=None,timeout=120,check=True):
        start=time.monotonic()
        p=subprocess.run(argv,input=stdin,text=True,capture_output=True,timeout=timeout,
                         env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','TMPDIR','DOCKER_CONFIG'}})
        report['commands'].append({'argv':argv,'exitCode':p.returncode,'seconds':round(time.monotonic()-start,3),
                                   'stdout':p.stdout,'stderr':p.stderr})
        if check and p.returncode: raise RuntimeError('Command failed: '+str(argv[:5]))
        return p

    def gate(name,ok,**details):
        report['gates'][name]={'status':'PASS' if ok else 'FAIL',**details}
        if not ok: raise AssertionError(name)

    def inspect(name): return json.loads(run(docker+['inspect',name]).stdout)[0]

    def probe(mode,network,image_id):
        results=output/mode
        results.mkdir()
        results.chmod(0o777)
        name=prefix+'-'+mode
        env={
            'SPRINGDOTENV_ENABLED':'false','APP_ENVIRONMENT':'production',
            'APP_WORKER_ENABLED':'false','APP_INVESTIGATION_WORKER_ENABLED':'false','MODEL_API_KEY':'',
            'EMBEDDING_MODEL_URI':'file:/models/model.onnx','EMBEDDING_TOKENIZER_URI':'file:/models/tokenizer.json',
            'EMBEDDING_REVISION':REVISION,'DB_URL':'jdbc:postgresql://127.0.0.1:5432/qualification',
            'APP_DB_USERNAME':'fixture_app','APP_DB_PASSWORD':'qualification-synthetic-only',
            'OWNER_DB_USERNAME':'fixture_owner','OWNER_DB_PASSWORD':'unused-synthetic-no-flyway',
            'JWT_SECRET':'qualification-only-synthetic-jwt-32bytes-minimum','SPRING_FLYWAY_ENABLED':'false',
            'SPRING_JPA_HIBERNATE_DDL_AUTO':'validate','SERVER_ADDRESS':'127.0.0.1','SERVER_PORT':'0',
            'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
        argv=docker+['run','--detach','--name',name,'--pull=never','--platform=linux/amd64',
             '--network',network,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true',
             '--user','10001:10001','--memory','1536m','--cpus','2','--pids-limit','256',
             '--tmpfs','/tmp:rw,exec,nosuid,size=384m,mode=1777',
             '--tmpfs','/runtime:rw,exec,nosuid,size=256m,uid=10001,gid=10001,mode=700',
             '--mount',f'type=bind,src={output / "harness"},dst=/qualification,readonly',
             '--mount',f'type=bind,src={args.models.resolve()},dst=/models,readonly',
             '--mount',f'type=bind,src={results},dst=/results']
        for key,value in env.items(): argv+=['--env',key+'='+value]
        argv+=['--entrypoint','/opt/java/openjdk/bin/java',image_id,'-Xmx512m','-Duser.home=/runtime',
               '-Dqualification.jar-sha256='+args.expected_jar_sha256,
               '-Dloader.main=qualification.ProductionProbe','-Dloader.path=/qualification',
               '-cp','/app/investigator.jar','org.springframework.boot.loader.launch.PropertiesLauncher',mode]
        run(argv);owned.append(name)
        container=inspect(name)
        (results/'container-inspect.json').write_text(json.dumps(container,indent=2)+'\n')
        gate(mode+'ImageIdentity',container['Image']==image_id)
        # Docker normalizes a shared network namespace from its name to its ID.
        expected_network=('container:'+inspect(network.removeprefix('container:'))['Id']
                          if network.startswith('container:') else network)
        gate(mode+'NetworkIsolation',container['HostConfig']['NetworkMode']==expected_network,
             observed=container['HostConfig']['NetworkMode'],expected=expected_network)
        gate(mode+'ReadOnlyRuntime',container['HostConfig']['ReadonlyRootfs']
             and container['Config']['User']=='10001:10001'
             and set(container['HostConfig']['Tmpfs'])=={'/tmp','/runtime'}
             and all(m['Destination']=='/results' or not m['RW'] for m in container['Mounts']))
        code=int(run(docker+['wait',name],timeout=240).stdout.strip())
        logs=run(docker+['logs',name])
        (results/'runtime.log').write_text(logs.stdout+logs.stderr)
        data=json.loads((results/(mode+'.json')).read_text())
        report[mode+'Probe']=data
        for dependency,member in NATIVES:
            expected=report['nativeLibraryHashes'][member]
            observed=[v for p,v in data['nativeLibrarySha256'].items() if Path(p).name==Path(member).name]
            gate(mode+'Native_'+Path(member).name,observed==[expected])
            gate(mode+'Loaded_'+Path(member).name,any('/'+Path(member).name in line
                 for line in data['loadedNativeMappings']))
        gate(mode+'InferenceAndChecks',code==0 and data['status']=='PASS' and all(c['status']=='PASS' for c in data['checks']),containerExitCode=code)
        if mode=='context': gate('productionApplicationContext',data.get('startupStatus')=='PASS')

    try:
        for name,(size,digest) in MODELS.items():
            path=args.models/name
            gate('pinned_'+name,not path.is_symlink() and path.stat().st_size==size and sha(path)==digest)
        image=json.loads(run(docker+['image','inspect',args.image]).stdout)[0]
        image_id=image['Id']
        gate('linuxAmd64',image['Os']=='linux' and image['Architecture']=='amd64')
        report['imageInspection']=image
        report['imageManifestDigest']=image.get('Descriptor',{}).get('digest')
        defaults=dict(value.split('=',1) for value in image['Config']['Env'])
        gate('imageOfflineDefaults',all(defaults.get(k)==v for k,v in {
            'DJL_DEFAULT_ENGINE':'Rust','DJL_OFFLINE':'true','OPT_OUT_TRACKING':'true',
            'DJL_CACHE_DIR':'/tmp/embedding-native'}.items()))
        archive=output/'image.tar'
        run(docker+['image','save','--output',str(archive),image_id])
        with tarfile.open(archive) as saved:
            manifest=json.load(saved.extractfile('manifest.json'))
            gate('singleSavedManifest',len(manifest)==1)
            config=saved.extractfile(manifest[0]['Config']).read()
            gate('exactConfigIdentity',hashlib.sha256(config).hexdigest()==args.expected_config_sha256)
        copyname=prefix+'-copy'
        run(docker+['create','--name',copyname,'--network','none','--pull=never','--read-only','--entrypoint','/opt/java/openjdk/bin/java',image_id,'--version'])
        owned.append(copyname)
        jar=output/'production.jar'
        run(docker+['cp',copyname+':/app/investigator.jar',str(jar)])
        gate('exactJarIdentity',sha(jar)==args.expected_jar_sha256)
        gate('baselineJarIdentity',sha(args.baseline_jar)=='bee5e753ee209754b417710670b224f1e7c302700b04f63013a524bd2a0773b5')
        def inventory(path,prefix):
            with zipfile.ZipFile(path) as z:
                return {n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')}
        gate('applicationAndMigrationsUnchanged',inventory(jar,'BOOT-INF/classes/')==inventory(args.baseline_jar,'BOOT-INF/classes/'))
        oldlibs=inventory(args.baseline_jar,'BOOT-INF/lib/')
        newlibs=inventory(jar,'BOOT-INF/lib/')
        gate('onlyExpectedDependencyRemoval',oldlibs.keys()-newlibs.keys()=={'BOOT-INF/lib/pytorch-engine-0.36.0.jar'}
             and not newlibs.keys()-oldlibs.keys() and all(newlibs[n]==oldlibs[n] for n in newlibs))
        unpacked=output/'unpacked'
        with zipfile.ZipFile(jar) as z:
            names=z.namelist()
            gate('uniqueJarEntries',len(names)==len(set(names)))
            libs=[n for n in names if n.startswith('BOOT-INF/lib/') and n.endswith('.jar')]
            gate('pytorchAdapterExcluded',not any('pytorch' in n.lower() for n in libs))
            for required in ['spring-ai-transformers-2.0.1.jar','api-0.36.0.jar','tokenizers-0.36.0.jar','onnxruntime-1.21.1.jar']:
                gate('pinnedDependency_'+required,'BOOT-INF/lib/'+required in libs)
            for name in names:
                if name.startswith(('BOOT-INF/classes/','BOOT-INF/lib/')) and not name.endswith('/'):
                    path=unpacked/name
                    gate('safeJarPath_'+name,not Path(name).is_absolute() and '..' not in Path(name).parts)
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(z.read(name))
        report['nativeLibraryHashes']={}
        for dependency,member in NATIVES:
            with zipfile.ZipFile(unpacked/'BOOT-INF/lib'/dependency) as z:
                report['nativeLibraryHashes'][member]=hashlib.sha256(z.read(member)).hexdigest()
        source=ROOT/'scripts/qualification/ProductionProbe.java'
        report['harnessSourceSha256']=sha(source)
        run(['javac','--release','21','-cp',str(unpacked/'BOOT-INF/classes')+os.pathsep+str(unpacked/'BOOT-INF/lib/*'),
             '-d',str(output/'harness'),str(source)])
        report['harnessClassSha256']=sha(output/'harness/qualification/ProductionProbe.class')
        probe('manual','none',image_id)
        dbname=prefix+'-db'
        run(docker+['run','--detach','--name',dbname,'--pull=never','--network','none','--read-only',
             '--user','postgres','--cap-drop=ALL','--security-opt=no-new-privileges:true',
             '--memory','384m','--cpus','1','--pids-limit','128',
             '--tmpfs','/var/lib/postgresql/data:rw,nosuid,noexec,size=192m,mode=1777',
             '--tmpfs','/var/run/postgresql:rw,nosuid,noexec,size=16m,mode=1777',
             '--tmpfs','/tmp:rw,nosuid,noexec,size=16m,mode=1777',
             '--env','PGDATA=/var/lib/postgresql/data/pgdata','--env','POSTGRES_DB=qualification',
             '--env','POSTGRES_USER=fixture_admin','--env','POSTGRES_PASSWORD=qualification-synthetic-admin-only',args.database_image])
        owned.append(dbname)
        database=inspect(dbname)
        report['databaseInspection']=database
        gate('syntheticDatabaseNetworkIsolation',database['HostConfig']['NetworkMode']=='none'
             and not database['HostConfig']['PortBindings'])
        for _ in range(60):
            if run(docker+['exec',dbname,'pg_isready','-h','127.0.0.1','-U','fixture_admin','-d','qualification'],check=False).returncode==0: break
            time.sleep(0.5)
        else: raise RuntimeError('Synthetic fixture did not become ready')
        fixture=ROOT/'scripts/qualification/embedding_startup_fixture.sql'
        report['syntheticFixtureSha256']=sha(fixture)
        run(docker+['exec','-i',dbname,'psql','-X','-v','ON_ERROR_STOP=1','-U','fixture_admin','-d','qualification'],stdin=fixture.read_text())
        probe('context','container:'+dbname,image_id)
        report['status']='PASS'
    except Exception as failure:
        report['status']='FAIL'
        report['failure']=str(failure)
    finally:
        cleanup=[]
        for name in reversed(owned):
            cleanup.append({'container':name,'exitCode':run(docker+['rm','--force',name],check=False).returncode})
        report['cleanup']=cleanup
        if any(c['exitCode']!=0 for c in cleanup): report['status']='FAIL'
        for name in ['manualInferenceAndChecks','contextInferenceAndChecks','productionApplicationContext']:
            report['gates'].setdefault(name,{'status':'UNVERIFIED','reason':'Not reached; inspect failure and preceding commands.'})
        report['evidenceHashes']={str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file() and p.suffix in {'.json','.log','.class'}}
        (output/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'report':str(output/'qualification.json')}))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__': sys.exit(main())
