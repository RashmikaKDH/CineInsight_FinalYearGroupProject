import os

import mysql.connector
from flask import Flask, redirect, render_template, request, session, url_for, jsonify, Response, stream_with_context
from werkzeug.security import check_password_hash, generate_password_hash
import yt_dlp
import json
from main import process_youtube_review_generator



app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cineinsight-dev-secret-key')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


@app.route('/')
def index():
    return render_template('index.html')


def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='cineinsight_db',
    )


@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            return render_template('signin.html', error='Please enter both email and password.')

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                'SELECT User_Id, Name, Email, Password, Role FROM `USER` WHERE Email = %s LIMIT 1',
                (email,)
            )
            user = cursor.fetchone()

            if user and check_password_hash(user['Password'], password):
                session.clear()
                session['user_id'] = user['User_Id']
                session['user_name'] = user['Name']
                session['user_email'] = user['Email']
                session['user_role'] = user['Role']
                return redirect(url_for('dashboard'))

            return render_template('signin.html', error='Invalid email or password.')
        except mysql.connector.Error:
            return render_template('signin.html', error='Database error. Please try again.')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template('signin.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not name or not email or not password:
            return render_template('signup.html', error='Please fill in all required fields.')

        if password != confirm_password:
            return render_template('signup.html', error='Passwords do not match.')

        hashed_password = generate_password_hash(password)

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute('SELECT 1 FROM `USER` WHERE Email = %s LIMIT 1', (email,))
            existing_user = cursor.fetchone()

            if existing_user:
                return render_template('signup.html', error='An account with this email already exists.')

            cursor.execute(
                'INSERT INTO `USER` (Name, Email, Password) VALUES (%s, %s, %s)',
                (name, email, hashed_password)
            )
            connection.commit()
            return redirect(url_for('signin'))
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            return render_template('signup.html', error='Database error. Please try again.')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template('signup.html')


@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@app.route('/analysis')
def analysis():
    return render_template('analysis.html')


@app.route('/forgot')
def forgot():
    return render_template('forgot.html')


@app.route('/google-login')
def google_login():
    return render_template('google-login.html')


@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')
    limit = request.args.get('limit', '8')  # Default to 8 results
    
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # ytsearchN fetches exactly N results
            search_query = f"ytsearch{limit}:{query}"
            info = ydl.extract_info(search_query, download=False)
            
            results = []
            if 'entries' in info:
                for entry in info['entries']:
                    duration = entry.get('duration')
                    if duration:
                        m, s = divmod(int(duration), 60)
                        h, m = divmod(m, 60)
                        if h > 0:
                            duration_str = f"{h}:{m:02d}:{s:02d}"
                        else:
                            duration_str = f"{m}:{s:02d}"
                    else:
                        duration_str = "N/A"
                        
                    views = entry.get('view_count')
                    view_str = "0 views"
                    if views:
                        if views >= 1000000:
                            view_str = f"{(views/1000000):.1f}M views"
                        elif views >= 1000:
                            view_str = f"{(views/1000):.1f}K views"
                        else:
                            view_str = f"{views} views"

                    thumbs = entry.get('thumbnails', [])
                    thumb_url = thumbs[-1]['url'] if thumbs else '../static/assets/dune_thumb.png'

                    results.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'url': entry.get('url'),
                        'duration_str': duration_str,
                        'view_str': view_str,
                        'thumbnail': thumb_url
                    })
            return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze')
def api_analyze():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    def generate():
        try:
            for json_str in process_youtube_review_generator(url):
                # SSE format: "data: {json}\n\n"
                yield f"data: {json_str}\n\n"
        except Exception as e:
            error_json = json.dumps({"status": "error", "message": f"Pipeline Error: {str(e)}"})
            yield f"data: {error_json}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')



if __name__ == '__main__':
    app.run(debug=True)
    