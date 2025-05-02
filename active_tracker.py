from datetime import datetime
from pytz import timezone

KST = timezone("Asia/Seoul")
_last_user_active_time = datetime.now(KST)

def update_last_active():
    global _last_user_active_time
    _last_user_active_time = datetime.now(KST)

def get_last_active():
    return _last_user_active_time
