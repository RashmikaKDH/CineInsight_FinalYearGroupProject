import csv,io,json,tempfile,unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock,patch
from flask import Flask
from services import analysis_worker as worker,db_service as db
from services.report_import import reports
from src import local_inference as inference
ROOT=Path(__file__).resolve().parents[1]
class AutomatedFlowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.instance=self.tmp.name
  self.app=Flask(__name__,template_folder=str(ROOT/'templates'),instance_path=self.instance)
  self.app.secret_key='test';self.app.register_blueprint(worker.automation);self.app.register_blueprint(reports)
  for n in ['signin','dashboard','profile']:self.app.add_url_rule('/'+n,endpoint=n,view_func=lambda:'test')
  self.c=self.app.test_client()
  with self.c.session_transaction() as s:s['user_id']=1;s['analysis_token']='token'
  self.url='https://www.youtube.com/watch?v=test'
 def test_start_idempotence_owner_and_auth(self):
  with patch.object(db,'create_pending_analysis',return_value=12) as create,patch.object(worker.EXECUTOR,'submit') as submit:
   body={'url':self.url,'request_id':'request-123456789','token':'token'}
   for _ in range(2):self.assertEqual(self.c.post('/api/analyze/start',json=body).status_code,202)
   create.assert_called_once();submit.assert_called_once()
  r=self.c.get('/api/analyze/status/12');self.assertEqual(r.json['status'],'queued')
  self.assertNotIn('user_id',r.json)
  with self.c.session_transaction() as s:s['user_id']=2
  self.assertEqual(self.c.get('/api/analyze/status/12').status_code,404)
  self.assertEqual(self.c.post('/api/analyze/start',json={'token':'bad'}).status_code,400)
  with self.c.session_transaction() as s:s.clear()
  self.assertEqual(self.c.post('/api/analyze/start',json={}).status_code,401)
 def fixture(self):
  values=dict(segment_id='s1',start=0,end=2,text='<script>bad</script>',aspects='acting',primary_aspect='acting',sentiment_label='positive',aspect_sentiments='{"acting":"positive"}',sentiment_status='completed',sarcasm_prediction='Sarcastic',sarcastic_probability=.7,shap_status='completed',text_shap_value=.01,audio_shap_value=.1,video_shap_value=.1,ai_reasoning='Possible sarcasm.',reasoning_status='completed')
  out=io.StringIO();w=csv.DictWriter(out,fieldnames=list(values));w.writeheader();w.writerow(values);return out.getvalue().encode()
 def process(self,db_error=False,partial=False):
  work=worker.owner_dir(self.instance,1)/'12'
  worker.write_json(work/'task.json',dict(analysis_id=12,user_id=1,url=self.url,status='queued',process=worker.PROCESS))
  main=ModuleType('main')
  def prepare(url,work_dir):
   self.assertEqual(Path(work_dir),work/'prepared')
   yield json.dumps({'status':'progress','message':'Whisper'})
   yield json.dumps({'status':'completed','csv_path':'csv','video_path':'video','audio_path':'audio'})
  main.process_youtube_review_generator=prepare
  def run(args):
   args.progress_callback('Grouped SHAP')
   p=Path(args.output)/'inference_test';p.mkdir(parents=True)
   (p/'cineinsight_final_explainability_report.csv').write_bytes(self.fixture());return 2 if partial else 0
  with patch.dict('sys.modules',{'main':main}),patch.object(inference,'reasoning_config'),patch.object(inference,'run',side_effect=run),patch.object(db,'update_analysis_state'),patch.object(db,'save_final_analysis',side_effect=RuntimeError('down') if db_error else None) as save:
   worker.process_analysis(self.instance,1,12)
   state=worker.load_state(self.instance,1,12)
   return state,save
 def test_full_background_flow_saves_db_result_and_download(self):
  state,save=self.process();self.assertEqual(state['status'],'completed');self.assertTrue(state['db_saved'])
  self.assertEqual(save.call_args.args[:2],(1,12))
  page=self.c.get(state['result_url']);self.assertEqual(page.status_code,200);self.assertNotIn(b'<script>bad</script>',page.data)
  self.assertEqual(self.c.get(state['download_url']).status_code,200)
 def test_partial_and_database_failure_preserve_result(self):
  state,save=self.process(db_error=True,partial=True)
  self.assertEqual(state['status'],'partial');self.assertFalse(state['db_saved']);self.assertEqual(self.c.get(state['result_url']).status_code,200)
 def test_restart_does_not_restart_processing(self):
  folder=worker.owner_dir(self.instance,1)/'12'
  worker.write_json(folder/'task.json',dict(analysis_id=12,status='running',process='old'))
  self.assertEqual(worker.load_state(self.instance,1,12)['status'],'interrupted')
 def test_database_upsert_uses_one_transaction(self):
  connection=Mock();cursor=connection.cursor.return_value;cursor.fetchone.return_value={'Analysis_Id':12}
  summary={'sarcasm_rate':20,'overall':{'positive':50},'aspects':{},'sarcastic':1,'conclusion':'text','reasons':[]}
  with patch.object(db,'_get_connection',return_value=connection):db.save_final_analysis(1,12,summary,'id','completed')
  sql=' '.join(c.args[0] for c in cursor.execute.call_args_list)
  self.assertIn('FOR UPDATE',sql);self.assertIn('ON DUPLICATE KEY UPDATE',sql);self.assertNotIn('INSERT INTO analysis',sql)
  connection.commit.assert_called_once()
  cursor.fetchone.return_value=None
  with patch.object(db,'_get_connection',return_value=connection):
   with self.assertRaises(ValueError):db.save_final_analysis(2,12,summary,'id','completed')
  connection.rollback.assert_called_once()
if __name__=='__main__':unittest.main()
