import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from src import local_inference as li

class LocalInferenceTests(unittest.TestCase):
 def test_command_final_csv_and_preserved_inputs(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)
   for name in ['input.csv','video.mp4','audio.wav','model.pth','bg.npy','bg.json']:(p/name).write_bytes(b'test')
   args=SimpleNamespace(csv=str(p/'input.csv'),video=str(p/'video.mp4'),audio=str(p/'audio.wav'),model=str(p/'model.pth'),background=str(p/'bg.npy'),background_meta=str(p/'bg.json'),output=str(p/'runs'),device='cpu',gemini_model='test',skip_gemini=True)
   source="assert json.loads(json.dumps({'ok':True}))['ok']; results=pd.DataFrame([{'segment_id':'s1','sentiment_label':'positive','sarcasm_prediction':'Normal'}])"
   with patch.object(li,'STAGES',[('Synthetic integration fixture',source)]):code=li.run(args)
   self.assertEqual(code,0)
   folder=next((p/'runs').iterdir())
   self.assertEqual((folder/'inputs/segments.csv').read_bytes(),b'test')
   self.assertTrue((folder/'cineinsight_final_explainability_report.csv').exists())
   self.assertEqual(json.loads((folder/'status.json').read_text())['status'],'completed')
 def test_all_stages_compile_without_colab(self):
  for name,source in li.STAGES:
   compile(source,name,'exec')
   self.assertNotIn('google.colab',source)
 def test_dedicated_reasoning_key_and_model(self):
  import os
  with patch.dict(os.environ,{'SHAP_GEMINI_API_KEY':'separate-test-key','SHAP_GEMINI_MODEL':'separate-model','GEMINI_API_KEY':'aspect-key','GEMINI_MODEL':'aspect-model'},clear=True):
   self.assertEqual(li.reasoning_config(),('separate-test-key','separate-model'))
   self.assertEqual(li.reasoning_config('cli-model'),('separate-test-key','cli-model'))
  with patch.dict(os.environ,{'GEMINI_API_KEY':'aspect-key'},clear=True):
   with self.assertRaises(ValueError):li.reasoning_config()
   self.assertEqual(li.reasoning_config(enabled=False)[0],'')
 def test_relative_paths_use_project_root(self):
  self.assertEqual(li.project_path('data/example.csv'),(li.ROOT/'data/example.csv').resolve())
 def test_reasoning_stage_uses_dedicated_setting(self):
  source=dict(li.STAGES)['Gemini reasoning']
  self.assertIn('api_key = REASONING_API_KEY',source)
  self.assertNotIn("os.getenv('GEMINI_API_KEY'",source)
 def test_real_validation_stage(self):
  folder=li.ROOT/'data/local_inference/inference_20261014_035020_859139/inputs'
  if not (folder/'segments.csv').exists():self.skipTest('Real prepared fixture unavailable')
  assets=li.ROOT/'models/cineinsight'
  with tempfile.TemporaryDirectory() as d:
   args=SimpleNamespace(csv=str(folder/'segments.csv'),video=str(folder/'video.mp4'),audio=str(folder/'audio.wav'),model=str(assets/'cineinsight_crossmodal_attention_best.pth'),background=str(assets/'shap_background.npy'),background_meta=str(assets/'shap_background.json'),output=d,device='cpu',gemini_model=None,skip_gemini=True)
   stages=[li.STAGES[0],('Output fixture','results=segments.copy()')]
   with patch.object(li,'STAGES',stages):self.assertEqual(li.run(args),0)
   output=next(Path(d).iterdir())
   self.assertTrue((output/'manifest.json').exists())
   self.assertTrue((output/'validated_segments.csv').exists())
if __name__=='__main__':unittest.main()
