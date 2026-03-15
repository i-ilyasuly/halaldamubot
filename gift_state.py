# Уақытша state: {user_id: {"step": "awaiting_username"}}
# Серверде жадта сақталады, бот рестарт болса тазаланады — бұл жеткілікті
_states = {}

def set_awaiting_username(user_id):
    """Пайдаланушы @username енгізуін күту режимі"""
    _states[str(user_id)] = {"step": "awaiting_username"}

def is_awaiting_username(user_id):
    state = _states.get(str(user_id))
    return state and state.get("step") == "awaiting_username"

def set_confirm_username(user_id, username):
    """Username расталуын күту режимі"""
    _states[str(user_id)] = {"step": "confirm_username", "username": username}

def get_pending_username(user_id):
    state = _states.get(str(user_id))
    if state and state.get("step") == "confirm_username":
        return state.get("username")
    return None

def clear_state(user_id):
    _states.pop(str(user_id), None)
