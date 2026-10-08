import ast
import csv
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('extractor',ROOT/'src/extractors/llm_aspect_extractor.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class FakeClient:
    def __init__(self,errors=(),omit=False):
        self.models=self;self.calls=0;self.errors=list(errors);self.omit=omit
    def generate_content(self,**kwargs):
        self.calls+=1
        if self.errors:
            e=RuntimeError('test');e.code=self.errors.pop(0);raise e
        rows=json.loads(kwargs['contents'])
        output=[{'index':r['index'],'sentiment':'mixed','aspect_sentiments':[
            {'aspect':'acting','sentiment':'positive'},{'aspect':'plot','sentiment':'negative'}]} for r in rows]
        if self.omit:output=output[:-1]
        return SimpleNamespace(text=json.dumps(output),usage_metadata=None)
    def close(self):pass

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)
        for name,value in [('CACHE_DIR',self.p/'cache'),('LLM_DEBUG_TRACE_FILE',str(self.p/'trace.json'))]:
            patcher=patch.object(m,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.env=patch.dict(os.environ,{'GEMINI_API_KEY':'fake-test-only','GEMINI_REQUEST_GAP_SECONDS':'0','GEMINI_SEGMENTS_PER_REQUEST':'20','GEMINI_MAX_REQUESTS_PER_RUN':'20'})
        self.env.start();self.addCleanup(self.env.stop)
        self.sleep=patch.object(m.time,'sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
    def run_client(self,c,segments):
        with patch.object(m,'genai',SimpleNamespace(Client=lambda **kw:c)):
            return m.extract_aspects_from_segments_llm(segments)
    def test_batches_cache_and_mixed_aspects(self):
        segments=[{'segment_id':str(i),'text':f'Acting good plot bad {i}'} for i in range(98)]
        c=FakeClient();result=self.run_client(c,segments)
        self.assertEqual(c.calls,5)
        self.assertEqual(result[0]['aspect_sentiments'],{'acting':'positive','plot':'negative'})
        self.assertEqual(result[0]['sentiment_label'],'mixed')
        self.run_client(c,segments);self.assertEqual(c.calls,5)
        self.assertNotIn('sentiment_label',segments[0])
    def test_retry_503_but_not_429(self):
        c=FakeClient([503]);self.run_client(c,[{'text':'good'}]);self.assertEqual(c.calls,2)
        c=FakeClient([429,429])
        with self.assertRaises(RuntimeError):self.run_client(c,[{'text':'another'}])
        self.assertEqual(c.calls,1)
    def test_missing_and_duplicate_ids_rejected(self):
        with self.assertRaises(RuntimeError):self.run_client(FakeClient(omit=True),[{'text':'good'}])
        row={'index':0,'sentiment':'neutral','aspect_sentiments':[{'aspect':'general','sentiment':'neutral'}]}
        with self.assertRaises(ValueError):m._parse_response(json.dumps([row,row]),{0})
    def test_budget_and_resume(self):
        segments=[{'text':str(i)} for i in range(21)]
        with patch.dict(os.environ,{'GEMINI_MAX_REQUESTS_PER_RUN':'1'}):
            c=FakeClient()
            with self.assertRaises(RuntimeError):self.run_client(c,segments)
            self.assertEqual(c.calls,1)
        c=FakeClient();r=self.run_client(c,segments)
        self.assertEqual(c.calls,1);self.assertEqual(len(r),21)
    def test_csv_preserves_nested_labels(self):
        tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_save_llm_output_csv')
        from datetime import datetime
        ns={'csv':csv,'json':json,'os':os,'datetime':datetime,'LLM_CSV_OUTPUT_DIR':str(self.p)}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'main.py','exec'),ns)
        rows=self.run_client(FakeClient(),[{'segment_id':'s1','text':'good acting bad plot'}])
        path=ns['_save_llm_output_csv']('test',rows)
        with open(path,encoding='utf-8',newline='') as f:r=next(csv.DictReader(f))
        self.assertEqual(json.loads(r['aspect_sentiments']),{'acting':'positive','plot':'negative'})
        self.assertEqual(r['sentiment_status'],'completed')
    def test_empty_and_long_text(self):
        c=FakeClient();r=self.run_client(c,[{'text':''}]);self.assertEqual(c.calls,0)
        self.assertEqual(r[0]['sentiment_status'],'skipped_empty')
        with self.assertRaises(RuntimeError):self.run_client(c,[{'text':'x'*7001}])

if __name__=='__main__':unittest.main()
