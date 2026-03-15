# Уақытша state: {user_id: {"step": "...", ...}}
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

def set_pending_anon(user_id, gift_type, recipient_username=None):
    """Анонимді/атымен сұрауын күту — gift_type және recipient сақталады"""
    data = {"step": "awaiting_anon", "gift_type": gift_type}
    if recipient_username:
        data["recipient_username"] = recipient_username
    _states[str(user_id)] = data

def get_pending_anon(user_id):
    """Анонимді/атымен күтіп тұрса — (gift_type, recipient_username) қайтарады"""
    state = _states.get(str(user_id))
    if state and state.get("step") == "awaiting_anon":
        return state.get("gift_type"), state.get("recipient_username")
    return None, None

def clear_state(user_id):
    _states.pop(str(user_id), None)
