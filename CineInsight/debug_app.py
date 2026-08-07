import os
import json
from flask import Flask, jsonify, render_template

app = Flask(__name__)

TRACE_FILE = 'debug_trace.json'

@app.route('/')
def index():
    return render_template('debug_dashboard.html')

@app.route('/api/debug-search')
def debug_search():
    if not os.path.exists(TRACE_FILE):
        return jsonify({"error": "No trace file found. Please run a search in the main app first."})
        
    try:
        with open(TRACE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Starting Debug Pipeline on port 5001...")
    app.run(port=5001, debug=True)
