import json
import os

TRACE_FILE = 'debug_trace.json'

class TraceLogger:
    def __init__(self):
        self.query = ""
        self.trace_data = []

    def start_trace(self, query: str):
        self.query = query
        self.trace_data = []

    def add_video_log(self, video_id: str, video_log: dict):
        # Merge or append
        existing = next((v for v in self.trace_data if v["video_id"] == video_id), None)
        if existing:
            existing.update(video_log)
        else:
            self.trace_data.append(video_log)
            
    def get_video_log(self, video_id: str):
        return next((v for v in self.trace_data if v["video_id"] == video_id), None)

    def save_trace(self):
        data = {
            "query": self.query,
            "trace": self.trace_data
        }
        try:
            with open(TRACE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving trace: {e}")

# Global instance for the app
logger = TraceLogger()
