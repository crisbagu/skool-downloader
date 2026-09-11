"""Inventory from authenticated Skool page metadata; no playback tokens on disk."""
from html.parser import HTMLParser
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode, quote
from engine import emit, media_priority, redact

class NextDataParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('id')=='__NEXT_DATA__':self.active=True
    def handle_endtag(self,tag):
        if tag=='script':self.active=False
    def handle_data(self,data):
        if self.active:self.parts.append(data)

def html_props(html):
    parser=NextDataParser();parser.feed(html)
    if not parser.parts:raise RuntimeError('Skool no devolvió los datos del contenido. Revisa la sesión o vuelve a analizar.')
    return json.loads(''.join(parser.parts))['props']['pageProps']

def parse_target(url):
    u=urlsplit(url.strip()); parts=u.path.strip('/').split('/')
    if u.scheme!='https' or u.hostname not in ('skool.com','www.skool.com') or u.username or u.password or u.port not in (None,443) or any(x in ('.','..','') for x in parts) or parts[0] in ('login','signup','settings','discovery','onboarding'):
        raise ValueError('Pega una URL de comunidad, curso, lección o publicación de Skool.')
    if not re.fullmatch(r'[\w-]+',parts[0]):raise ValueError('Nombre de comunidad no válido.')
    base='https://www.skool.com/'+parts[0]
    kind='community'; target=base
    if len(parts)>=2 and parts[1]=='classroom':
        target=base+'/classroom'
        if len(parts)==3:
            kind='course';target+='/'+parts[2]
            if parse_qs(u.query).get('md'):
                kind='lesson';target+='?'+urlencode({'md':parse_qs(u.query)['md'][0]})
        elif len(parts)>3:raise ValueError('Ruta del aula no válida.')
    elif len(parts)==2 and parts[1] not in ('about','calendar','members'):
        kind='post';target=base+'/'+parts[1]
    elif len(parts)>2:raise ValueError('Usa la página principal, un curso o una publicación.')
    return {'base':base,'url':target,'kind':kind}

def stable_id(value):return hashlib.sha256(value.encode()).hexdigest()[:20]

def external_urls(value):
    result=[]
    def visit(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if not re.search(r'token|thumbnail|cover|image',k,re.I):visit(v)
        elif isinstance(x,list):
            for v in x:visit(v)
        elif isinstance(x,str):
            if x.startswith('[v2]'):x=x[4:]
            try:
                parsed=json.loads(x)
                if isinstance(parsed,(dict,list)):visit(parsed);return
            except (ValueError,TypeError):pass
            for raw in re.findall(r'https?://[^\s<>"\[\]\\]+',x):
                raw=raw.rstrip(".,);'")
                u=urlsplit(raw)
                if media_priority(raw) or u.hostname in ('youtu.be','vimeo.com','www.vimeo.com'):
                    # Signed HLS URLs expire: they must be resolved on the original page, not persisted.
                    if u.path.endswith(('.m3u8','.mpd','.mp4','.webm')) and u.query:continue
                    if 'youtube' in (u.hostname or ''):
                        q=parse_qs(u.query); raw=urlunsplit((u.scheme,u.netloc,u.path,urlencode({'v':q['v'][0]}) if q.get('v') else '', ''))
                    if raw not in result:result.append(raw)
    visit(value);return result

def media_specs(metadata):
    specs=[]; ids=[]
    raw=metadata.get('videoIds') or metadata.get('videoId') or ''
    if isinstance(raw,list):ids=raw
    elif isinstance(raw,str):ids=re.split(r'[,\s]+',raw.strip())
    for ident in ids:
        if ident and ident not in [s.get('video_id') for s in specs]:specs.append({'video_id':ident,'media_hint':'','media_key':'native:'+ident})
    # Only video/embed fields and rich content; do not count resource/PDF attachments as videos.
    fields={k:v for k,v in metadata.items() if k in ('videoLink','videoUrl','videoLinksData','desc','content','embed','video')}
    for url in external_urls(fields):specs.append({'video_id':'','media_hint':url,'media_key':'external:'+url})
    return specs

def make_item(spec,url,title,source,accessible=True):
    return {**spec,'id':stable_id(url+'#'+spec['media_key']),'url':url,'title':title or 'Video sin título','source':source,'accessible':accessible,'status':'pending' if accessible else 'locked','downloads':{}}

def course_items(props,url):
    tree=props.get('course') or {}; root=tree.get('course') or {}; root_meta=root.get('metadata') or {}
    if not root:raise RuntimeError('Skool no devolvió este curso: puede estar bloqueado o haber cambiado.')
    title=root_meta.get('title','Curso'); accessible=root_meta.get('hasAccess',1)!=0
    items=[];lessons=0
    def walk(node):
        nonlocal lessons
        obj=node.get('course',{});meta=obj.get('metadata',{})
        if obj.get('unitType')=='module':
            lessons+=1
            for spec in media_specs(meta):
                items.append(make_item(spec,url.split('?')[0]+'?'+urlencode({'md':obj['id']}),meta.get('title'),title,accessible and meta.get('hasAccess',1)!=0))
        for child in node.get('children',[]):walk(child)
    for node in tree.get('children',[]):walk(node)
    return {'items':items,'lessons':lessons,'title':title,'accessible':accessible,'declared_lessons':root_meta.get('numModules',lessons)}

def post_items(tree,base):
    post=tree.get('post',{});meta=post.get('metadata',{})
    if not post.get('name'):return []
    url=base+'/'+post['name'];title=meta.get('title') or post['name'].replace('-',' ')
    return [make_item(spec,url,title,'Publicaciones',meta.get('hasAccess',1)!=0) for spec in media_specs(meta)]

def playback_url(props,video_id):
    matches=[]
    def walk(x):
        if isinstance(x,dict):
            if x.get('id')==video_id and x.get('playbackId'):
                token=x.get('playbackToken');url='https://stream.video.skool.com/'+quote(x['playbackId'],safe='')+'.m3u8'
                matches.append(url+('?'+urlencode({'token':token}) if token else ''))
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(props);return matches[0] if matches else None

def save_catalog(data,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(path)

def load_catalog(path):return json.loads(Path(path).read_text())

class SkoolSession:
    def __init__(self,context,page):self.context=context;self.page=page
    def login(self,base,timeout=600):
        from playwright.sync_api import TimeoutError as PWTimeout
        emit('status',message='Abriendo Skool. Si aparece el acceso, inicia sesión en esta ventana.')
        try:self.page.goto(base,wait_until='domcontentloaded',timeout=45000)
        except PWTimeout:pass
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if self.page.is_closed():raise RuntimeError('Cerraste el navegador. Vuelve a analizar para continuar.')
            try:
                p=html_props(self.page.content())
                if (p.get('self') or {}).get('id'):return
            except (ValueError,KeyError,RuntimeError):pass
            self.page.wait_for_timeout(700)
        raise RuntimeError('No se confirmó la sesión. Inicia sesión en el navegador de la app y vuelve a intentar.')
    def read(self,url):
        last=None
        for attempt in range(3):
            try:
                response=self.context.request.get(url,timeout=45000)
                if response.status in (401,403):raise PermissionError('Sin acceso al contenido o sesión caducada.')
                if response.status==429 or response.status>=500:
                    last=RuntimeError('Skool limita temporalmente las consultas. Inténtalo más tarde.')
                    self.page.wait_for_timeout((attempt+1)*1500);continue
                if not response.ok:raise RuntimeError('Skool respondió con HTTP '+str(response.status))
                props=html_props(response.text())
                return props
            except PermissionError:raise
            except Exception as exc:
                last=exc
                if attempt<2:self.page.wait_for_timeout(1000*(attempt+1))
        raise RuntimeError(redact(str(last)))

def scan(session,target,scope,path):
    old={}
    if Path(path).exists():
        try:old={i['id']:i for i in load_catalog(path).get('items',[])}
        except (ValueError,KeyError):pass
    data={'version':2,'target':target['url'],'scope':scope,'scanned_at':time.strftime('%Y-%m-%d %H:%M:%S'),'items':[],'lessons':0,'courses':0,'posts':0,'warnings':[],'complete':False}
    known=set()
    def add(items):
        for item in items:
            if item['id'] in known:continue
            previous=old.get(item['id'],{})
            item['downloads']=previous.get('downloads',{})
            known.add(item['id']);data['items'].append(item)
        save_catalog(data,path)
        emit('inventory',catalog=data,message=f"{len(data['items'])} videos encontrados · analizando…")
    if target['kind'] in ('course','lesson'):
        urls=[target['url'].split('?')[0]]
    elif target['kind']=='community' and scope in ('all','courses'):
        props=session.read(target['base']+'/classroom');courses=props.get('allCourses')
        if not isinstance(courses,list):raise RuntimeError('El aula no devolvió un catálogo. Comprueba que puedes abrir los cursos.')
        urls=[target['base']+'/classroom/'+c['name'] for c in courses if c.get('name')]
    else:urls=[]
    for n,url in enumerate(urls,1):
        emit('status',message=f'Analizando curso {n}/{len(urls)}…')
        try:
            result=course_items(session.read(url),url)
            data['courses']+=1;data['lessons']+=result['lessons']
            if not result['accessible']:data['warnings'].append(result['title']+': curso sin acceso; conteo interior no confirmado.')
            elif result['lessons']<result['declared_lessons']:data['warnings'].append(result['title']+': faltan lecciones en la respuesta de Skool.')
            items=result['items']
            if target['kind']=='lesson':items=[i for i in items if parse_qs(urlsplit(i['url']).query).get('md')==parse_qs(urlsplit(target['url']).query).get('md')]
            add(items)
        except Exception as exc:data['warnings'].append(f'Curso {n}: '+redact(str(exc)))
    if target['kind']=='post':
        props=session.read(target['url']);tree=props.get('postTree')
        if not tree:raise RuntimeError('La publicación no está disponible para esta sesión.')
        data['posts']=1;add(post_items(tree,target['base']))
    elif target['kind']=='community' and scope in ('all','posts'):
        seen=set(); page_number=1; page_size=None
        while True:
            try:
                props=session.read(target['base']+('?p='+str(page_number) if page_number>1 else ''))
                trees=props.get('postTrees')
                if not isinstance(trees,list):raise RuntimeError('No se recibió el listado de publicaciones.')
                non_pinned=[t for t in trees if not t.get('post',{}).get('metadata',{}).get('pinned')]
                if page_size is None:page_size=len(non_pinned) or len(trees) or 30
                fresh=[t for t in trees if t.get('post',{}).get('id') not in seen]
                for tree in fresh:
                    ident=tree.get('post',{}).get('id')
                    if ident:seen.add(ident)
                    add(post_items(tree,target['base']))
                data['posts']=len(seen)
                total=props.get('total',0)
                emit('status',message=f'Publicaciones: {len(seen)} revisadas · página {page_number} · {len(data["items"])} videos')
                if not trees or len(non_pinned)<page_size:break
                if not fresh:
                    data['warnings'].append('La paginación repitió una página; el conteo de publicaciones es parcial.');break
                if total and page_number>=math.ceil(total/page_size):break
                page_number+=1
                if page_number>10000:
                    data['warnings'].append('Se alcanzó el límite de 10.000 páginas; inventario parcial.');break
                session.page.wait_for_timeout(250)
            except Exception as exc:
                data['warnings'].append('Publicaciones: '+redact(str(exc)));break
    data['complete']=not data['warnings'];data['unique_videos']=len({i['media_key'] for i in data['items']})
    save_catalog(data,path)
    emit('inventory',catalog=data,message=f"Análisis {'completo' if data['complete'] else 'parcial'}: {len(data['items'])} videos · {data['courses']} cursos · {data['posts']} publicaciones")
    return data

def run_batch(data,selected,quality,download,path):
    selected=set(selected);queue=[i for i in data['items'] if i['id'] in selected];counts={'completed':0,'skipped':0,'failed':0}
    for index,item in enumerate(queue,1):
        emit('item',id=item['id'],status='downloading',message=f'{index}/{len(queue)} · {item["title"]}')
        cached=item.get('downloads',{}).get(quality)
        if cached and Path(cached).is_file() and Path(cached).stat().st_size>0:
            counts['skipped']+=1;item['status']='complete'
        else:
            # 'accessible' proviene del árbol del curso y puede venir conservador para un admin:
            # no nos rendimos antes de intentar; le preguntamos a Skool y reportamos su respuesta real.
            locked=not item.get('accessible',True)
            try:
                result=download(item)
                item.setdefault('downloads',{})[quality]=str(result);item['status']='complete';item.pop('error',None);counts['completed']+=1
                if locked:emit('status',message=f'Desbloqueado: «{item["title"]}» sí tenía acceso.')
            except PermissionError:
                counts['failed']+=1;item['status']='locked'
                item['error']='Bloqueo real de Skool: el servidor no entrega este vídeo a tu cuenta (nivel insuficiente o sin acceso).'
            except Exception as exc:
                counts['failed']+=1;msg=redact(str(exc))
                if locked and re.search(r'no proporcion|reproducci',str(exc),re.I):
                    item['status']='locked';item['error']='Skool abrió la lección pero no incluyó el vídeo: bloqueo del servidor para tu cuenta.'
                else:
                    item['status']='failed';item['error']=msg
        save_catalog(data,path)
        emit('item',id=item['id'],status=item['status'],message=item.get('error') or f'{index}/{len(queue)} · {item["title"]}')
        emit('batch_progress',percent=index*100/max(len(queue),1))
    emit('batch_done',**counts,message=f'Lote terminado: {counts["completed"]} descargados, {counts["skipped"]} existentes, {counts["failed"]} fallidos.')
    return counts
