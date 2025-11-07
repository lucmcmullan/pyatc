import queue
import pyttsx3
import threading
 
RESPONSE_VOICE = True

_engine = pyttsx3.init()
_engine.setProperty("rate", 175)
_engine.setProperty("volume", 0.9)

_queue: "queue.Queue[str]" = queue.Queue()

def _worker():
    while True:
        text = _queue.get()
        if text is None:
            break
        try:
            _engine.say(text)
            _engine.runAndWait()
        except Exception:
            pass
        _queue.task_done()

_thread = threading.Thread(target=_worker, daemon=True)
_thread.start()

def speak(text: str):
    """Queue text to be spoken asynchronously."""
    if not RESPONSE_VOICE:
        return
    if not text:
        return
    _queue.put(str(text))