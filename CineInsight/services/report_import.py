"""Validated final CSV reports, stored per signed-in user without schema changes."""
import csv
import io
import json
import math
import hashlib
from collections import Counter
from pathlib import Path
from flask import Blueprint, current_app, session, request, render_template, redirect, url_for, abort

reports = Blueprint('reports', __name__)
ASPECTS = ('acting','plot','cgi','direction','music','dialogue','general')
LABELS = {'positive','neutral','negative','mixed','uncertain','not_applicable'}
SCORED = {'positive','neutral','negative','mixed'}
LIMIT = 5 * 1024 * 1024

def summarize(rows):
    counts=Counter(rows)
    denominator=sum(counts[x] for x in SCORED)
    return {'counts':dict(counts),'total':denominator,'excluded':len(rows)-denominator,
            'positive':round(100*counts['positive']/denominator,1) if denominator else None}

def parse_report(raw):
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        required={'segment_id','start','end','text','aspects','primary_aspect','sentiment_label',
                  'aspect_sentiments','sentiment_status','sarcasm_prediction','sarcastic_probability',
                  'shap_status','text_shap_value','audio_shap_value','video_shap_value','ai_reasoning','reasoning_status'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Upload the final Colab report containing sentiment, predictions and SHAP results, not the first local CSV.')
        rows=list(reader)
        if not rows or len(rows)>20000: raise ValueError('The report must contain 1â€“20,000 segments.')
        seen=set();sentiments=[];aspect_labels={a:[] for a in ASPECTS};reasons=[];sarcastic=0;warnings=0
        for row in rows:
            sid=row['segment_id']
            if not sid or sid in seen: raise ValueError('Missing or duplicate segment IDs.')
            seen.add(sid)
            try:
                start,end=float(row['start']),float(row.get('effective_end') or row['end'])
                probability=float(row['sarcastic_probability'])
            except ValueError:
                raise ValueError('The report contains invalid timestamps or probabilities.') from None
            if not all(math.isfinite(x) for x in (start,end,probability)) or start<0 or end<=start or not 0<=probability<=1:
                raise ValueError('Invalid timestamps or probabilities.')
            if row['sarcasm_prediction'] not in ('Normal','Sarcastic'): raise ValueError('Incomplete model predictions.')
            aspects=row['aspects'].split('|')
            try:
                mapping=json.loads(row['aspect_sentiments'])
            except ValueError:
                raise ValueError('Aspect sentiment data is invalid. Export the final CSV again from Colab.') from None
            if not isinstance(mapping,dict) or set(mapping)!=set(aspects) or not set(aspects)<=set(ASPECTS) or row['primary_aspect'] not in aspects:
                raise ValueError('Aspect labels do not match the aspect sentiments.')
            if row['sentiment_label'] not in LABELS or any(v not in LABELS for v in mapping.values()):
                raise ValueError('Invalid sentiment labels.')
            if row['sentiment_status'] in ('completed','completed_with_warnings'):
                sentiments.append(row['sentiment_label'])
                for aspect,label in mapping.items():aspect_labels[aspect].append(label)
                warnings+=row['sentiment_status']=='completed_with_warnings'
            else:sentiments.append('unavailable')
            if row['sarcasm_prediction']=='Sarcastic':
                sarcastic+=1;effects=[]
                if row['shap_status']=='completed':
                    try:
                        values=[float(row[a+'_shap_value']) for a in ('text','audio','video')]
                    except ValueError:
                        raise ValueError('The report contains invalid SHAP contributions.') from None
                    if not all(math.isfinite(v) for v in values):raise ValueError('Invalid SHAP values.')
                    for aspect,value in zip(('Text','Audio','Video'),values):
                        effects.append({'name':aspect,'value':value,'direction':'supports sarcasm' if value>0 else 'opposes sarcasm' if value<0 else 'no measured contribution'})
                reasons.append({'id':sid,'start':start,'end':end,'text':row['text'],'aspects':aspects,
                    'probability':round(probability*100,1),'effects':effects,
                    'explanation':row['ai_reasoning'] if row['reasoning_status']=='completed' else '',
                    'available':row['reasoning_status']=='completed'})
        overall=summarize(sentiments)
        breakdown={a:summarize(labels) for a,labels in aspect_labels.items()}
        rate=round(100*sarcastic/len(rows),1)
        conclusion=(f"{overall['positive']}% of classified review segments were positive. " if overall['positive'] is not None else 'No sentiment score is available. ')
        conclusion+=f"The model flagged {sarcastic} of {len(rows)} analyzed segments ({rate}%) as sarcastic. Sentiment and sarcasm are separate predictions."
        return {'total':len(rows),'sarcastic':sarcastic,'sarcasm_rate':rate,'overall':overall,'aspects':breakdown,
                'reasons':reasons,'conclusion':conclusion,'warnings':warnings}
    except (UnicodeError,csv.Error,TypeError,KeyError,OverflowError) as exc:
        raise ValueError('The CSV contains missing or invalid data. Export it again from Colab.') from exc

def store_dir():
    if 'user_id' not in session:abort(401)
    owner=hashlib.sha256(str(session['user_id']).encode()).hexdigest()
    path=Path(current_app.instance_path)/'imported_reports'/owner
    path.mkdir(parents=True,exist_ok=True)
    return path

def analysis_history(user_id):
    from services.db_service import get_analyses_for_user
    return get_analyses_for_user(user_id)

@reports.route('/reports',methods=['GET','POST'])
def library():
    if 'user_id' not in session:return redirect(url_for('signin'))
    if request.content_length and request.content_length > LIMIT + 1024 * 1024:
        return render_template('reports.html',error='Choose a CSV smaller than 5 MB.',history=[]), 413
    folder=store_dir();error=None
    analyses=[]
    try:
        analyses=analysis_history(session['user_id'])
    except Exception:
        current_app.logger.exception('Could not load analysis history')
        error='Analysis history is temporarily unavailable. Please try again later.'
    selected_id=request.form.get('analysis_id',request.args.get('analysis_id',''))
    if request.method=='POST':
        import secrets
        if not secrets.compare_digest(str(request.form.get('token','')),str(session.get('report_token','missing'))):abort(400)
        try:
            upload=request.files.get('report')
            selected=next((a for a in analyses if str(a['Analysis_Id'])==selected_id),None)
            if selected is None:raise ValueError(error or 'Select a video from your analysis history.')
            title=selected.get('YouTube_url','')
            if not title:raise ValueError('This analysis has no saved video URL.')
            if not upload or not upload.filename.lower().endswith('.csv'):raise ValueError('Choose a final Colab CSV file.')
            raw=upload.stream.read(LIMIT+1)
            if len(raw)>LIMIT:raise ValueError('Choose a CSV smaller than 5 MB.')
            data=parse_report(raw);identity=hashlib.sha256(str(selected['Analysis_Id']).encode()+b'\0'+raw).hexdigest()
            target=folder/(identity+'.json')
            if not target.exists():
                data.update(title=title,id=identity,analysis_id=selected['Analysis_Id'],video_url=title,analysis_date=str(selected.get('Analysis_Date','')))
                temp=target.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(target)
                (folder/(identity+'.csv')).write_bytes(raw)
            return redirect(url_for('reports.show',report_id=identity))
        except ValueError as exc:error=str(exc)
    import secrets
    session.setdefault('report_token',secrets.token_urlsafe(32))
    history=[]
    for path in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            data=json.loads(path.read_text(encoding='utf-8'));history.append({'id':data['id'],'title':data['title']})
        except (ValueError,KeyError):continue
    return render_template('reports.html',error=error,history=history,analyses=analyses,selected_id=selected_id)

@reports.route('/reports/<report_id>')
def show(report_id):
    if 'user_id' not in session:return redirect(url_for('signin'))
    if len(report_id)!=64 or any(c not in '0123456789abcdef' for c in report_id):abort(404)
    path=store_dir()/(report_id+'.json')
    if not path.exists():abort(404)
    return render_template('report_results.html',report=json.loads(path.read_text(encoding='utf-8')))
