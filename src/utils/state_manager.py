import os
import json
from src.config import BASE_DIR

STATE_FILE_PATH = os.path.join(BASE_DIR, "data", "state.json")

def load_state():
    if not os.path.exists(STATE_FILE_PATH):
        return None
    try:
        with open(STATE_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE_PATH), exist_ok=True)
    with open(STATE_FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=4)

def init_state(urls):
    state = {
        "urls": [{"url": url, "status": "pending", "time_spent": 0.0, "error": None} for url in urls],
        "stats": {
            "total_processed": 0,
            "total_success": 0,
            "total_failed": 0,
            "avg_time_per_item": 0.0
        }
    }
    save_state(state)
    return state

def update_item_status(url, status, time_spent=0.0, error=None):
    state = load_state()
    if not state:
        return
    
    updated = False
    for item in state["urls"]:
        if item["url"] == url:
            item["status"] = status
            item["time_spent"] = time_spent
            item["error"] = error
            updated = True
            break
            
    if updated:
        # Recalculate stats
        success_count = sum(1 for item in state["urls"] if item["status"] in ("success", "filled_awaiting_manual"))
        failed_count = sum(1 for item in state["urls"] if item["status"] == "failed")
        processed_count = sum(1 for item in state["urls"] if item["status"] != "pending")
        
        times = [item["time_spent"] for item in state["urls"] if item["time_spent"] > 0]
        avg_time = sum(times) / len(times) if times else 0.0
        
        state["stats"] = {
            "total_processed": processed_count,
            "total_success": success_count,
            "total_failed": failed_count,
            "avg_time_per_item": round(avg_time, 2)
        }
        save_state(state)
    return state

def clear_state():
    if os.path.exists(STATE_FILE_PATH):
        try:
            os.remove(STATE_FILE_PATH)
        except Exception:
            pass
