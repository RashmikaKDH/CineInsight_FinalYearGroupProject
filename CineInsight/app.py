import os
import tempfile
from functools import wraps

import mysql.connector
from flask import Flask, redirect, render_template, request, session, url_for, jsonify, Response, stream_with_context, flash
from werkzeug.security import check_password_hash, generate_password_hash
import yt_dlp
import json
from main import process_youtube_review_generator

# ---------------------------------------------------------------------------
# Search pipeline service imports
# ---------------------------------------------------------------------------
from services.youtube_search import search_movie_reviews
from services.subtitle_service import download_subtitles, cleanup_subtitle_files
from services.subtitle_parser import parse_vtt_to_text
from services.language_detector import get_detector
from services.trace_logger import logger


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cineinsight-dev-secret-key')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# YouTube Data API v3 key (set in environment or .env file)
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', '')



# ---------------------------------------------------------------------------
# Access Control Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Redirect to sign-in if the user is not authenticated."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('signin'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Allow access only to Admin-role users."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('signin'))
        if session.get('user_role') != 'Admin':
            return redirect(url_for('profile'))
        return f(*args, **kwargs)
    return decorated_function


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

        if len(password) < 8:
            return render_template('signup.html', error='Password must be at least 8 characters long.')

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
            flash('Account created successfully! Please sign in.', 'success')
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
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/analysis')
def analysis():
    return render_template('analysis.html')


@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        import re
        email = request.form.get('email', '').strip().lower()

        # 1. Email format validation
        if not email:
            return render_template('forgot.html', error='Please enter your email address.')

        email_pattern = re.compile(r'^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$')
        if not email_pattern.match(email):
            return render_template('forgot.html', error='Please enter a valid email address.')

        # 2. Database user existence check
        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute('SELECT User_Id, Name FROM `USER` WHERE Email = %s LIMIT 1', (email,))
            user = cursor.fetchone()
        except mysql.connector.Error:
            return render_template('forgot.html', error='Database error. Please try again.')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        if not user:
            return render_template('forgot.html', error='No account found with that email address.')

        # 3. User exists — show success state
        return render_template('forgot.html', success=True, email=email)

    return render_template('forgot.html')


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # 1. Basic field validation
        if not email:
            return render_template('reset-password.html', error='Email is missing. Please go back and try again.', email=email)

        if not password or not confirm_password:
            return render_template('reset-password.html', error='Please fill in all required fields.', email=email)

        # 2. Password strength validation
        if len(password) < 8:
            return render_template('reset-password.html', error='Password must be at least 8 characters long.', email=email)

        # 3. Password match validation
        if password != confirm_password:
            return render_template('reset-password.html', error='Passwords do not match.', email=email)

        # 4. Verify the user actually exists in the database
        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute('SELECT User_Id FROM `USER` WHERE Email = %s LIMIT 1', (email,))
            user = cursor.fetchone()
        except mysql.connector.Error:
            return render_template('reset-password.html', error='Database error. Please try again.', email=email)
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        if not user:
            return render_template('reset-password.html', error='No account found with that email. Please restart the reset process.', email=email)

        # 5. All checks passed — update the password
        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            hashed_password = generate_password_hash(password)
            cursor.execute('UPDATE `USER` SET Password = %s WHERE Email = %s', (hashed_password, email))
            connection.commit()
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            return render_template('reset-password.html', error='Database error. Please try again.', email=email)
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        return render_template('reset-password.html', success=True)

    # GET — pass email from query param so the hidden field is pre-filled
    email = request.args.get('email', '')
    return render_template('reset-password.html', email=email)


@app.route('/google-login')
def google_login():
    return render_template('google-login.html')


@app.route('/api/search')
def api_search():
    """
    New search pipeline:
      1. YouTube Data API v3  → top 20 movie review videos
      2. yt-dlp               → subtitle download only (no video)
      3. subtitle_parser      → .vtt → plain text
      4. fastText             → English detection
      5. Return first 8 English videos
    """
    query = request.args.get('q', '')
    duration = request.args.get('duration', 'medium')  # 'any','short','medium','long'
    # Validate to prevent arbitrary API params
    if duration not in ('any', 'short', 'medium', 'long'):
        duration = 'medium'
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    # --- Check API key ---
    if not YOUTUBE_API_KEY:
        return jsonify({
            'error': 'YOUTUBE_API_KEY is not configured. '
                     'Set it as an environment variable.'
        }), 500

    # --- Load fastText detector (lazy, singleton) ---
    try:
        detector = get_detector()
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500

    # --- Step 1: YouTube Data API v3 search → top 50 videos ---
    try:
        candidates = search_movie_reviews(query, max_results=50, video_duration=duration)
    except (ValueError, RuntimeError) as e:
        return jsonify({'error': str(e)}), 500

    results          = []
    total_processed  = 0
    TARGET           = 8

    # Use a single temp directory for all subtitle downloads this request
    with tempfile.TemporaryDirectory() as tmp_dir:
        for video in candidates:
            if len(results) >= TARGET:
                break

            video_id = video['video_id']
            total_processed += 1
            
            # Fetch the log dictionary created by youtube_search.py
            vlog = logger.get_video_log(video_id)
            if not vlog:
                continue

            # --- Step 2: Download subtitles (no video download) ---
            try:
                vtt_path, subtitle_type = download_subtitles(video_id, tmp_dir)
                vlog["subtitle_status"] = subtitle_type
            except Exception:
                vlog["subtitle_status"] = "error"
                continue   # Network/permission error — skip this video

            if vtt_path is None:
                # No subtitles available — skip
                vlog["subtitle_status"] = "none"
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            # --- Step 3: Parse .vtt → plain text ---
            try:
                transcript = parse_vtt_to_text(vtt_path)
                vlog["transcript_snippet"] = transcript[:500] if transcript else ""
            except Exception:
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            if not transcript or len(transcript.strip()) < 30:
                # Empty or near-empty transcript — skip
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            # --- Step 4: fastText language detection ---
            try:
                lang_info = detector.detect_with_score(transcript)
                vlog["layer4_detected_lang"] = lang_info.get('lang', 'unknown')
                vlog["layer4_score"] = lang_info.get('score', 0.0)
                vlog["layer4_lang_pass"] = (vlog["layer4_detected_lang"] == 'en')
            except Exception:
                vlog["layer4_lang_pass"] = False
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            if not vlog["layer4_lang_pass"]:
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            # --- Step 5: English video confirmed — add to results ---
            vlog["final_status"] = "accepted"
            results.append({
                'video_id':     video_id,
                'title':        video['title'],
                'channel':      video['channel'],
                'thumbnail':    video['thumbnail'],
                'duration':     video['duration'],
                'published':    video['published'],
                'url':          video['url'],
                'transcript':   transcript
            })
            
            cleanup_subtitle_files(tmp_dir, video_id)

    # Save the trace to disk for debug_app to read
    logger.save_trace()

    return jsonify({
        'query':           query,
        'total_processed': total_processed,
        'english_videos':  len(results),
        'results':         results,
    })


import re

def is_english_review(title):
    if not title:
        return False
    # Reject Non-Latin scripts (Hindi/Devanagari, Tamil, Telugu, Malayalam, Sinhala, CJK, Arabic, Cyrillic, etc.)
    non_latin_pattern = re.compile(r'[\u0900-\u0DFF\u0E00-\u0E7F\u0D80-\u0DFF\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\u0600-\u06FF\u0400-\u04FF]')
    if non_latin_pattern.search(title):
        return False

    # Reject explicit non-English language tags in video title
    non_english_tags = [
        'hindi', 'tamil', 'telugu', 'malayalam', 'kannada', 'sinhala',
        'marathi', 'bengali', 'punjabi', 'gujarati', 'urdu', 'korean',
        'japanese', 'spanish', 'french', 'german', 'italian', 'russian', 'chinese', 'bahasa'
    ]
    title_lower = title.lower()
    for tag in non_english_tags:
        if re.search(r'\b' + re.escape(tag) + r'\b', title_lower):
            return False

    return True


TRENDING_CACHE = {
    'timestamp': 0,
    'data': []
}

@app.route('/api/trending-reviews')
def api_trending_reviews():
    import time
    current_time = time.time()
    # Cache results for 30 minutes (1800 seconds) for fast page load
    if TRENDING_CACHE['data'] and (current_time - TRENDING_CACHE['timestamp']) < 1800:
        return jsonify({'results': TRENDING_CACHE['data']})

    query = "trending english movie review"
    requested_limit = int(request.args.get('limit', '8'))
    # Fetch extra items from YouTube search to filter down to English-only reviews
    fetch_limit = requested_limit * 3

    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch{fetch_limit}:{query}"
            info = ydl.extract_info(search_query, download=False)

            results = []
            if 'entries' in info:
                for entry in info['entries']:
                    title = entry.get('title', '')
                    
                    # Filter out non-English reviews
                    if not is_english_review(title):
                        continue

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
                        'title': title,
                        'url': entry.get('url'),
                        'duration_str': duration_str,
                        'view_str': view_str,
                        'thumbnail': thumb_url
                    })

                    # Stop once we have reached the requested limit of English reviews
                    if len(results) >= requested_limit:
                        break

            TRENDING_CACHE['timestamp'] = current_time
            TRENDING_CACHE['data'] = results
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


# ---------------------------------------------------------------------------
# Debug — LLM Aspect Extraction Viewer
# ---------------------------------------------------------------------------

@app.route('/debug/aspect')
def debug_aspect():
    """Standalone debug UI to inspect the last LLM aspect extraction result."""
    return render_template('debug_aspect.html')


@app.route('/api/debug/aspect-data')
def api_debug_aspect_data():
    """Return the latest debug_aspect_trace.json written by the pipeline."""
    trace_path = os.path.join(os.path.dirname(__file__), 'debug_aspect_trace.json')
    if not os.path.exists(trace_path):
        return jsonify({'error': 'No trace file found. Run an analysis first.'}), 404
    try:
        with open(trace_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'Could not read trace: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# Profile & Admin Routes
# ---------------------------------------------------------------------------

@app.route('/profile')
@login_required
def profile():
    """Show the logged-in user's profile details."""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            'SELECT User_Id, Name, Email, Role FROM `USER` WHERE User_Id = %s',
            (session['user_id'],)
        )
        user = cursor.fetchone()
        return render_template('profile.html', user=user)
    except mysql.connector.Error:
        return redirect(url_for('dashboard'))
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@app.route('/admin')
@admin_required
def admin_panel():
    """Admin-only: list all registered users."""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute('SELECT User_Id, Name, Email, Role FROM `USER` ORDER BY User_Id ASC')
        users = cursor.fetchall()
        return render_template('admin.html', users=users)
    except mysql.connector.Error:
        return render_template('admin.html', users=[], error='Database error.')
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@app.route('/admin/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """Admin-only: permanently delete a user account."""
    # Prevent admin from deleting their own account
    if user_id == session.get('user_id'):
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin_panel'))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Fetch user before deletion to get their name for the message
        cursor.execute('SELECT Name FROM `USER` WHERE User_Id = %s', (user_id,))
        target = cursor.fetchone()

        if not target:
            flash('User not found.', 'error')
            return redirect(url_for('admin_panel'))

        cursor.execute('DELETE FROM `USER` WHERE User_Id = %s', (user_id,))
        connection.commit()
        flash(f"User '{target['Name']}' was deleted successfully.", 'success')
    except mysql.connector.Error:
        if connection: connection.rollback()
        flash('Database error. Could not delete user.', 'error')
    finally:
        if cursor: cursor.close()
        if connection: connection.close()

    return redirect(url_for('admin_panel'))


@app.route('/logout', methods=['POST'])
def logout():
    """Clear session and redirect to sign-in."""
    session.clear()
    return redirect(url_for('signin'))


if __name__ == '__main__':
    app.run(debug=True)
    