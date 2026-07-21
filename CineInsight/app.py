from flask import Flask, render_template

# Flask app eka initialize kirima
app = Flask(__name__)

# 1. Home / Search Screen ekata route eka
@app.route('/')
def home():
    # templates folder eke thiyena index.html eka render karanawa
    return render_template('index.html')

# 2. Login Screen ekata route eka
@app.route('/login')
def login():
    # templates folder eke thiyena login.html eka render karanawa
    return render_template('login.html')

# 3. Registration Screen ekata route eka
@app.route('/register')
def register():
    # templates folder eke thiyena register.html eka render karanawa
    return render_template('register.html')

# App eka run karana code eka
if __name__ == '__main__':
    app.run(debug=True)
    