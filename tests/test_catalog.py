import unittest
import tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog

class CatalogTests(unittest.TestCase):
    def test_scan_all_pages_deduplicates_pinned_posts_and_excludes_text_lessons(self):
        def post(ident,pinned=False):
            return {'post':{'id':ident,'name':ident,'metadata':{'title':ident,'pinned':int(pinned),'videoIds':ident+'video'}}}
        responses={
            'https://www.skool.com/demo/classroom':{'allCourses':[{'name':'c'}]},
            'https://www.skool.com/demo/classroom/c':{'course':{'course':{'name':'c','metadata':{'title':'C','numModules':2}},'children':[
                {'course':{'id':'a','unitType':'module','metadata':{'videoId':'v'}}},
                {'course':{'id':'b','unitType':'module','metadata':{'title':'Texto'}}}]}},
            'https://www.skool.com/demo':{'total':2,'postTrees':[post('pin',True),post('first')]},
            'https://www.skool.com/demo?p=2':{'total':2,'postTrees':[post('pin',True),post('last')]}}
        class Session:
            page=None
            def __init__(self):self.page=self
            def read(self,url):return responses[url]
            def wait_for_timeout(self,ms):pass
        with tempfile.TemporaryDirectory() as tmp:
            result=catalog.scan(Session(),catalog.parse_target('https://www.skool.com/demo'),'all',Path(tmp)/'catalog.json')
        self.assertTrue(result['complete'])
        self.assertEqual(result['lessons'],2)
        self.assertEqual(result['posts'],3)
        self.assertEqual(len(result['items']),4)

    def test_signed_playback_is_resolved_fresh_for_the_requested_video(self):
        props={'postTree':{'videos':[{'id':'one','playbackId':'a','playbackToken':'new-token'},{'id':'two','playbackId':'b','playbackToken':'other-token'}]}}
        self.assertEqual(catalog.playback_url(props,'one'),'https://stream.video.skool.com/a.m3u8?token=new-token')
        self.assertIsNone(catalog.playback_url(props,'missing'))

    def test_target_community_course_post_and_spoofing(self):
        self.assertEqual(catalog.parse_target('https://www.skool.com/demo')['kind'],'community')
        self.assertEqual(catalog.parse_target('https://www.skool.com/demo/classroom/abc')['kind'],'course')
        self.assertEqual(catalog.parse_target('https://www.skool.com/demo/welcome')['kind'],'post')
        for url in ('https://skool.com.evil/demo','https://www.skool.com/login','https://www.skool.com/demo/../login'):
            with self.assertRaises(ValueError): catalog.parse_target(url)

    def test_nested_modules_count_videos_not_pdf_and_preserve_access(self):
        props={'course':{'course':{'name':'abc','metadata':{'title':'Curso','hasAccess':1}},'children':[
            {'course':{'id':'one','unitType':'module','metadata':{'title':'Video','videoId':'native','hasAccess':1}}},
            {'course':{'id':'pdf','unitType':'module','metadata':{'title':'PDF','resources':'[{"file_name":"x.pdf"}]'}}},
            {'course':{'unitType':'folder'},'children':[{'course':{'id':'two','unitType':'module','metadata':{'title':'Embed','videoLink':'https://youtu.be/abcd','hasAccess':0}}}]}]}}
        result=catalog.course_items(props,'https://www.skool.com/demo/classroom/abc')
        self.assertEqual(result['lessons'],3)
        self.assertEqual(len(result['items']),2)
        self.assertEqual(result['items'][0]['video_id'],'native')
        self.assertFalse(result['items'][1]['accessible'])

    def test_post_multiple_videos_deduplicates_ids_and_does_not_store_tokens(self):
        tree={'post':{'id':'post','name':'welcome','metadata':{'title':'Hola','videoIds':'a,b,a','videoLinksData':'[{"url":"https://www.youtube.com/watch?v=xyz"}]'}},'videos':[{'id':'a','playbackId':'x','playbackToken':'SECRET'}]}
        items=catalog.post_items(tree,'https://www.skool.com/demo')
        self.assertEqual(len(items),3)
        self.assertNotIn('SECRET',str(items))
        self.assertEqual(len({x['id'] for x in items}),3)

    def test_batch_skips_valid_completed_file_continues_after_error_and_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'done.mp4';out.write_bytes(b'existing')
            items=[{'id':'a','title':'A','accessible':True,'downloads':{'best':str(out)}}, {'id':'b','title':'B','accessible':True}, {'id':'c','title':'C','accessible':True}]
            data={'items':items};calls=[]
            def download(item):
                calls.append(item['id'])
                if item['id']=='b':raise RuntimeError('Provider error')
                p=Path(tmp)/'new.mp4';p.write_bytes(b'complete');return p
            report=catalog.run_batch(data,['a','b','c'],'best',download,Path(tmp)/'catalog.json')
            self.assertEqual(calls,['b','c'])
            self.assertEqual(report,{'completed':1,'skipped':1,'failed':1})
            saved=catalog.load_catalog(Path(tmp)/'catalog.json')
            self.assertEqual(saved['items'][1]['status'],'failed')
            self.assertEqual(saved['items'][2]['status'],'complete')

if __name__=='__main__':unittest.main()
