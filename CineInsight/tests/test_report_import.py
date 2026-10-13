import io,json,tempfile,sys,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flask import Flask
from services.report_import import reports,parse_report
ROOT=Path(__file__).resolve().parents[1]
class ReportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.app=Flask(__name__,template_folder=str(ROOT/'templates'),static_folder=str(ROOT/'static'),instance_path=self.tmp.name)
  self.app.secret_key='test-only';self.app.register_blueprint(reports)
  for name in ['signin','dashboard','profile']:self.app.add_url_rule('/'+name,endpoint=name,view_func=lambda:'test')
  self.history_patch=patch('services.report_import.analysis_history',return_value=[{'Analysis_Id':7,'YouTube_url':'https://www.youtube.com/watch?v=test','Analysis_Date':'2026-10-08'}])
  self.mock_history=self.history_patch.start();self.addCleanup(self.history_patch.stop)
  self.client=self.app.test_client()
  with self.client.session_transaction() as s:s['user_id']=1;s['report_token']='token'
  header='segment_id,start,end,text,aspects,primary_aspect,sentiment_label,aspect_sentiments,sentiment_status,sarcasm_prediction,sarcastic_probability,shap_status,text_shap_value,audio_shap_value,video_shap_value,ai_reasoning,reasoning_status\n'
  row='s1,0,2,<script>alert(1)</script>,plot,plot,positive,"{""plot"":""positive""}",completed,Sarcastic,0.6,completed,-0.01,0.03,0.04,Sample,completed\n'
  self.raw=(header+row).encode()
 def upload(self,raw=None):return self.client.post('/reports',data={'token':'token','analysis_id':'7','report':(io.BytesIO(raw or self.raw),'final.csv')})
 def test_import_render_and_duplicate(self):
  r=self.upload();self.assertEqual(r.status_code,302)
  page=self.client.get(r.location);self.assertEqual(page.status_code,200)
  self.assertIn(b'100.0%',page.data);self.assertNotIn(b'<script>alert(1)</script>',page.data)
  self.assertEqual(self.upload().location,r.location)
  self.assertEqual(len(list(Path(self.tmp.name).rglob('*.json'))),1)
  with self.client.session_transaction() as s:s['user_id']=2
  self.assertEqual(self.client.get(r.location).status_code,404)
 def test_validation_and_auth(self):
  with self.assertRaises(ValueError):parse_report(b'segment_id,text\ns1,test')
  with self.assertRaises(ValueError):parse_report(self.raw+self.raw.split(b'\n')[1]+b'\n')
  self.assertEqual(self.client.post('/reports',data={'token':'bad'}).status_code,400)
  with self.client.session_transaction() as s:s.clear()
  self.assertEqual(self.client.get('/reports').status_code,302)
 def test_history_selection_and_rejection(self):
  page=self.client.get('/reports?analysis_id=7')
  self.assertIn(b'value="7" selected',page.data)
  self.assertNotIn(b'name="title"',page.data)
  r=self.upload();page=self.client.get(r.location)
  self.assertIn(b'https://www.youtube.com/watch?v=test',page.data)
  saved=json.loads(next(Path(self.tmp.name).rglob('*.json')).read_text(encoding='utf-8'))
  self.assertEqual(saved['analysis_id'],7)
  self.mock_history.return_value=[]
  response=self.upload()
  self.assertEqual(response.status_code,200)
  self.assertIn(b'Select a video from your analysis history.',response.data)
 def test_history_unavailable(self):
  self.mock_history.side_effect=RuntimeError('database down')
  response=self.upload()
  self.assertIn(b'temporarily unavailable',response.data)
  self.assertEqual(len(list(Path(self.tmp.name).rglob('*.json'))),0)
 def test_actual_report(self):
  path=Path('C:/Users/Rashmika/Downloads/cineinsight_final_explainability_report (6).csv')
  if not path.exists():self.skipTest('User fixture unavailable')
  r=parse_report(path.read_bytes());self.assertEqual(r['total'],191);self.assertEqual(r['sarcastic'],21);self.assertEqual(r['sarcasm_rate'],11.0)
  self.assertEqual(len(r['reasons']),21)
if __name__=='__main__':unittest.main()
