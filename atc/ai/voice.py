import queue
import pyttsx3
import threading
from concurrent.futures import ThreadPoolExecutor
 
RESPONSE_VOICE_ENABLED = False

def _create_engine():
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.setProperty("volume", 0.9)
    return engine

def _speak_text(text: str):
    try:
        engine = _create_engine()
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception:
        pass

_executor = ThreadPoolExecutor(max_workers=3)
_queue: "queue.Queue[str]" = queue.Queue()

def set_voice_enabled(enabled: bool):
    global RESPONSE_VOICE_ENABLED
    RESPONSE_VOICE_ENABLED = enabled

def _queue_worker():
    while True:
        text = _queue.get()
        if text is None:
            break
        if RESPONSE_VOICE_ENABLED and text.strip():
            _executor.submit(_speak_text, text)
        _queue.task_done()

_thread = threading.Thread(target=_queue_worker, daemon=True)
_thread.start()

def speak(text: str):
    """Queue text to be spoken asynchronously."""
    if not RESPONSE_VOICE_ENABLED or not text:
        return
    _queue.put(str(text))

def shutdown():
    _queue.put(None)
    _executor.shutdown(wait=True)