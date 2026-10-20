from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from pathlib import Path
import pypdfium2 as pdfium
out=Path('output/pdf'); out.mkdir(parents=True,exist_ok=True)
for name,file in [('Regular','arial.ttf'),('Bold','arialbd.ttf')]: pdfmetrics.registerFont(TTFont(name,'C:/Windows/Fonts/'+file))
p=out/'CineInsight_Showcase_60x150cm.pdf'
s=72/2.54/10
c=canvas.Canvas(str(p),pagesize=(600*s,1500*s)); c.scale(s,s)
c.setTitle('CineInsight | Project Showcase | 60 x 150 cm'); c.setAuthor('Team CodePulse')
navy='#13263C'; orange='#E85A25'; cream='#F6F5F0'; muted='#526579'; teal='#117E78'; white='#FFFFFF'
def rect(x,y,w,h,color,r=0):
 c.setFillColor(HexColor(color)); c.setStrokeColor(HexColor(color)); (c.roundRect(x,1500-y-h,w,h,r,stroke=0,fill=1) if r else c.rect(x,1500-y-h,w,h,stroke=0,fill=1))
def text(x,y,t,size=12,color=navy,font='Regular'):
 c.setFillColor(HexColor(color)); c.setFont(font,size); c.drawString(x,1500-y-size,t)
def wrap(x,y,t,width,size=12,color=navy,font='Regular',leading=None):
 leading=leading or size*1.4; words=t.split(); lines=[]; line=''
 for word in words:
  test=(line+' '+word).strip()
  if pdfmetrics.stringWidth(test,font,size)>width and line: lines.append(line); line=word
  else: line=test
 if line: lines.append(line)
 for i,line in enumerate(lines):text(x,y+i*leading,line,size,color,font)
 return y+len(lines)*leading
def label(y,n,title):
 text(30,y,n,11,orange,'Bold'); text(57,y-3,title,22,navy,'Bold')
def arrow(x,y):
 c.setStrokeColor(HexColor(orange));c.setLineWidth(1.7);c.line(x,1500-y,x,1500-y-13);c.line(x-4,1500-y-9,x,1500-y-13);c.line(x+4,1500-y-9,x,1500-y-13)
rect(0,0,600,1500,cream)
rect(0,0,600,250,navy); rect(30,32,38,32,orange,6)
for i in range(3):
 c.setStrokeColor(HexColor(white)); c.setLineWidth(2);c.line(36+i*9,1500-39,42+i*9,1500-44)
text(79,30,'CineInsight',34,white,'Bold');text(32,88,'HEAR THE WORDS. SEE THE CONTEXT.',12,'#FFB18F','Bold')
text(30,117,'When praise hides sarcasm.',30,white,'Bold')
wrap(30,164,'Multimodal Sarcasm-aware Sentiment Analysis for YouTube Movie Reviews',530,20,white,'Bold',26)
text(30,226,'TEAM CODEPULSE   /   PROJECT SHOWCASE',10,'#BCD0DF','Bold')
label(276,'01','The problem')
wrap(30,312,'A positive sentence can carry a negative meaning. Movie reviewers use tone and visual cues that text alone can miss, making sentiment scores difficult to interpret.',540,14)
label(392,'02','Our approach')
wrap(30,429,'Bring words, voice and video together to detect sarcasm, summarize movie aspects and explain the model\'s decision.',540,14)
for x,num,title,body in [(30,'1','Understand context','Combine three modalities for sarcasm detection.'),(214,'2','Reveal opinions','Summarize sentiment for each movie aspect.'),(398,'3','Explain evidence','Turn SHAP evidence into readable explanations.')]:
 rect(x,485,172,111,white,9);text(x+12,496,num,15,orange,'Bold');text(x+12,524,title,14,navy,'Bold');wrap(x+12,547,body,148,11)
label(623,'03','From review to insight')
rect(30,663,540,49,navy,8);text(45,674,'YouTube review',16,white,'Bold');text(249,680,'Download media + Whisper transcript',11,white)
arrow(300,715)
rect(30,736,260,74,white,8);text(44,748,'Aspect & sentiment analysis',14,navy,'Bold');wrap(44,772,'Gemini labels transcript segments by aspect and sentiment.',230,11)
rect(310,736,260,74,white,8);text(324,748,'Multimodal feature extraction',13,navy,'Bold');wrap(324,772,'Aligned text, audio and visual representations.',230,11)
for x,title,sub in [(310,'TEXT','DistilRoBERTa'),(398,'AUDIO','Wav2Vec2'),(486,'VIDEO','ViT')]:
 rect(x,820,84,53,'#E2EBED',6);text(x+8,828,title,10,teal,'Bold');text(x+8,849,sub,9,navy)
arrow(440,878)
rect(310,899,260,62,navy,8);text(324,909,'Crossmodal attention',15,white,'Bold');text(324,935,'Trained sarcasm classifier',12,white)
arrow(440,965)
rect(310,985,260,76,white,8);text(324,996,'SHAP + Gemini',15,teal,'Bold');wrap(324,1021,'Modality contributions become evidence-based explanations.',230,11)
rect(30,829,260,232,'#E8EFEB',8);text(45,847,'WHAT THE USER SEES',11,teal,'Bold')
for y,title,sub in [(881,'Aspect scores','Acting, plot, visuals and more'),(934,'Overall sentiment','Positive share of classified segments'),(987,'Sarcasm & reasoning','Flagged segments with explanations')]:
 text(45,y,title,15,navy,'Bold');wrap(45,y+25,sub,228,11)
text(30,1073,'One automated local workflow. Results saved to a personal report.',11,muted)
label(1110,'04','Results & outcomes')
for x,value,title,sub in [(30,'69.23%','Held-out test accuracy','104 balanced test samples'),(214,'0.69','Macro F1-score','Two-class sarcasm evaluation'),(398,'3 modalities','One integrated model','Text + audio + video')]:
 rect(x,1150,172,94,white,8);text(x+12,1162,value,25,teal,'Bold');text(x+12,1198,title,11,navy,'Bold');text(x+12,1220,sub,9,muted)
rect(30,1256,540,68,navy,8);text(44,1267,'LOCAL DEMONSTRATION',10,'#FFB18F','Bold')
text(44,1287,'95 segments',17,white,'Bold');text(224,1287,'10 sarcasm flags',17,white,'Bold');text(427,1287,'10 explanations',14,white,'Bold')
text(30,1335,'Personal accounts  /  Saved reports  /  Final CSV export',12,navy,'Bold')
text(30,1360,'Test metrics: EC06 evaluation. Demonstration counts describe one review, not accuracy.',8.5,muted)
rect(0,1390,600,110,navy)
text(30,1403,'TEAM CODEPULSE',12,'#FFB18F','Bold')
text(30,1425,'K. D. H. Rashmika  •  R. D. M. N. Premathilaka',10,white)
text(30,1442,'S. W. L. B. Sandaruwan  •  P. G. H. B. Upasena',10,white)
text(30,1465,'Supervisor: Mr. K. H. A. Hettige',10,'#BCD0DF')
text(355,1405,'Department of Computing',10,white,'Bold')
text(355,1426,'Faculty of Applied Sciences',10,white)
wrap(355,1446,'Rajarata University of Sri Lanka',215,11,white,'Bold')
c.showPage();c.save()
doc=pdfium.PdfDocument(str(p)); page=doc[0]; im=page.render(scale=0.65).to_pil();im.save(out/'CineInsight_Showcase_preview.png')
print(str(p.resolve())); print('Page size cm:',page.get_width()/72*2.54,page.get_height()/72*2.54)
