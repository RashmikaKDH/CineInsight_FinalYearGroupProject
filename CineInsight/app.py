import os
from functools import wraps

import mysql.connector
from flask import Flask, redirect, render_template, request, session, url_for, jsonify, Response, stream_with_context, flash
from werkzeug.security import check_password_hash, generate_password_hash
import yt_dlp
import json
from main import process_youtube_review_generator


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cineinsight-dev-secret-key')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


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
    