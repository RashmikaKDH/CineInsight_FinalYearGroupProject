"""Preparation contract: files for Colab, never dummy local tensors."""
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
class PreparationTests(unittest.TestCase):
 def load(self):
  pipeline=ModuleType('pipeline');pipeline.download_video=Mock(return_value='video.mp4')
  transcriber=ModuleType('src.transcriber');transcriber.extract_audio=Mock(return_value='audio.wav')
  transcriber.generate_transcript=Mock(return_value=[{'segment_id':'s1','start':0,'end':2,'text':'Great acting'}])
  llm=ModuleType('src.extractors.llm_aspect_extractor')
  llm.extract_aspects_from_segments_llm=Mock(return_value=[{'segment_id':'s1','start':0,'end':2,'text':'Great acting','aspects':['acting'],'sentiment_label':'positive','aspect_sentiments':{'acting':'positive'},'sentiment_status':'completed','sentiment_model':'test'}])
  spec=importlib.util.spec_from_file_location('prep_under_test',ROOT/'main.py');m=importlib.util.module_from_spec(spec)
  with patch.dict(sys.modules,{'pipeline':pipeline,'src.transcriber':transcriber,'src.extractors.llm_aspect_extractor':llm}):spec.loader.exec_module(m)
  return m,pipeline,transcriber,llm
 def test_files_and_csv_remain_without_tensor_functions(self):
  m,p,t,l=self.load()
  with tempfile.TemporaryDirectory() as d:
   m.LLM_CSV_OUTPUT_DIR=d;m.DEBUG_ASPECT_TRACE_FILE=str(Path(d)/'trace.json')
   events=[json.loads(x) for x in m.process_youtube_review_generator('https://youtu.be/test')]
   done=events[-1];self.assertEqual(done['status'],'completed')
   self.assertEqual(done['preparation_status'],'ready_for_colab')
   self.assertTrue(Path(done['csv_path']).is_file())
   self.assertEqual(done['video_path'],'video.mp4');self.assertEqual(done['audio_path'],'audio.wav')
   self.assertTrue({'text_shape','audio_shape','video_shape','raw_text_snippet'}.isdisjoint(done))
   t.generate_transcript.assert_called_once_with('audio.wav');l.extract_aspects_from_segments_llm.assert_called_once()
   self.assertIn('sentiment_label',Path(done['csv_path']).read_text())
 def test_gemini_failure_does_not_complete(self):
  m,p,t,l=self.load();l.extract_aspects_from_segments_llm.side_effect=RuntimeError('quota')
  events=[json.loads(x) for x in m.process_youtube_review_generator('url')]
  self.assertEqual(events[-1]['status'],'error')
  self.assertFalse(any(x['status']=='completed' for x in events))
 def test_downloader_has_no_feature_library_imports(self):
  import ast
  tree=ast.parse((ROOT/'pipeline.py').read_text(encoding='utf-8'))
  imports=[]
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):imports.extend(x.name.split('.')[0] for x in node.names)
   if isinstance(node,ast.ImportFrom):imports.append((node.module or '').split('.')[0])
  self.assertTrue(set(imports).isdisjoint({'torch','transformers','cv2','numpy','librosa','youtube_transcript_api'}))
if __name__=='__main__':unittest.main()
