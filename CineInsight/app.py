from flask import Flask, render_template

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/signin')
def signin():
    return render_template('signin.html')


@app.route('/signup')
def signup():
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


if __name__ == '__main__':
    app.run(debug=True)
    