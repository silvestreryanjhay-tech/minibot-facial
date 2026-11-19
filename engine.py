"""
Face recognition engine for the Mini-Bot.

Pipeline (see the "How it works" page):
  capture frame -> shrink + BGR->RGB -> detect faces (HOG) -> encode (128 numbers)
  -> compare with enrolled faces -> recognized / unknown -> log, buzzer, dashboard

If the `face_recognition` library is not installed (or DEMO=1), the engine runs in DEMO mode:
the site works exactly the same, but detections are simulated so you can test the design.
"""
import json
import os
import threading
import time
import uuid
from collections import deque

import cv2
import numpy as np

try:
    import face_recognition
    HAVE_FR = True
except Exception:  # not installed, or dlib missing
    face_recognition = None
    HAVE_FR = False

from buzzer import Buzzer
from camera import Camera

BASE = os.path.dirname(os.path.abspath(__file__))
KNOWN_DIR = os.path.join(BASE, "known_faces")
PEOPLE_JSON = os.path.join(KNOWN_DIR, "people.json")

GREEN = (95, 145, 18)    # BGR of #12915F
RED = (54, 54, 217)      # BGR of #D93636
UNKNOWN_SECONDS = 1.0    # unknown face must stay this long before the buzzer fires
ALERT_COOLDOWN = 6.0     # seconds between buzzer alerts
SEEN_COOLDOWN = 8.0      # seconds before the same person is logged again


class Engine:
    def __init__(self):
        os.makedirs(KNOWN_DIR, exist_ok=True)
        self.camera = Camera()
        self.buzzer = Buzzer()
        self.lock = threading.Lock()
        self.demo = (not HAVE_FR) or os.environ.get("DEMO") == "1"

        self.running = False
        self.thread = None
        self.tolerance = 0.5          # lower = stricter matching
        self.buzzer_enabled = True
        self.fps = 0.0

        self.people = {}              # id -> {id, name, role, image, encoding}
        self.events = deque(maxlen=200)
        self.snaps = {}               # event id -> jpeg bytes
        self.stats = {"recognized": 0, "unknown": 0, "buzzer": 0}
        self.state = {"status": "offline", "name": None, "role": None, "score": None, "since": time.time()}

        self.frame_jpeg = None
        self.face_jpeg = None
        self.face_version = 0
        self.last_raw = None

        self._seq = 0
        self._last_face_time = 0
        self._face_stamp = 0
        self._unknown_since = None
        self._last_alert = 0
        self._last_seen = {}
        self._placeholder = {}

        self._load_people()
        self.start()

    # ------------------------------------------------------------------ people
    def _load_people(self):
        if not os.path.exists(PEOPLE_JSON):
            return
        try:
            with open(PEOPLE_JSON, "r", encoding="utf-8") as fh:
                items = json.load(fh)
        except Exception:
            return
        for item in items:
            path = os.path.join(KNOWN_DIR, item["image"])
            if not os.path.exists(path):
                continue
            enc = None
            if not self.demo:
                img = face_recognition.load_image_file(path)
                found = face_recognition.face_encodings(img)
                if not found:
                    continue
                enc = found[0]
            self.people[item["id"]] = {**item, "encoding": enc}

    def _save_people(self):
        items = [{k: v for k, v in p.items() if k != "encoding"} for p in self.people.values()]
        with open(PEOPLE_JSON, "w", encoding="utf-8") as fh:
            json.dump(items, fh, indent=2)

    def add_person(self, name, role, image_bgr):
        """Enroll a new face from a BGR image. Raises ValueError with a readable message."""
        enc = None
        if not self.demo:
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb)
            if not locs:
                raise ValueError("No face found in that photo. Use a clear, front-facing picture.")
            if len(locs) > 1:
                raise ValueError("More than one face found. Use a photo with only one person.")
            enc = face_recognition.face_encodings(rgb, locs)[0]
        pid = uuid.uuid4().hex[:8]
        filename = pid + ".jpg"
        cv2.imwrite(os.path.join(KNOWN_DIR, filename), image_bgr)
        person = {"id": pid, "name": name, "role": role, "image": filename}
        self.people[pid] = {**person, "encoding": enc}
        self._save_people()
        self._event("info", f"{name} enrolled", role or "No role set")
        return person

    def remove_person(self, pid):
        person = self.people.pop(pid, None)
        if not person:
            return False
        try:
            os.remove(os.path.join(KNOWN_DIR, person["image"]))
        except OSError:
            pass
        self._save_people()
        self._event("info", f"{person['name']} removed", "Face deleted from the database")
        return True

    def list_people(self):
        return [{k: v for k, v in p.items() if k != "encoding"} for p in self.people.values()]

    # ----------------------------------------------------------------- control
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self._event("info", "Mini-Bot started", "Demo mode" if self.demo else "Live face recognition")

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self.state = {"status": "offline", "name": None, "role": None, "score": None, "since": time.time()}
        self._unknown_since = None
        self._event("info", "Mini-Bot stopped", "Camera processing paused")

    # --------------------------------------------------------------- main loop
    def _loop(self):
        faces, i, t0, n = [], 0, time.time(), 0
        while self.running:
            frame = self.camera.read()
            if frame is None:
                time.sleep(0.05)
                continue
            self.last_raw = frame.copy()
            i += 1
            if i % 2 == 1:  # detect on every 2nd frame to keep the Pi cool
                faces = self._detect_demo(frame) if self.demo else self._detect(frame)
            if self.demo and self.camera.kind == "synthetic" and faces:
                self._draw_cartoon(frame, faces[0]["box"])
            self._update(frame, faces)
            out = self._annotate(frame, faces)
            ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                self.frame_jpeg = buf.tobytes()
            n += 1
            if time.time() - t0 >= 1:
                self.fps = n / (time.time() - t0)
                n, t0 = 0, time.time()

    # --------------------------------------------------------------- detection
    def _detect(self, frame):
        small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        locs = face_recognition.face_locations(rgb, model="hog")
        encs = face_recognition.face_encodings(rgb, locs)
        faces = []
        for (t, r, b, l), enc in zip(locs, encs):
            pid, dist = self._match(enc)
            faces.append(self._face(pid, dist, (t * 4, r * 4, b * 4, l * 4)))
        return faces

    def _match(self, enc):
        known = [p for p in self.people.values() if p["encoding"] is not None]
        if not known:
            return None, None
        dists = face_recognition.face_distance([p["encoding"] for p in known], enc)
        k = int(np.argmin(dists))
        if dists[k] <= self.tolerance:
            return known[k]["id"], float(dists[k])
        return None, float(dists[k])

    def _detect_demo(self, frame):
        """Simulated scene: nobody -> registered person -> stranger, repeating."""
        h, w = frame.shape[:2]
        phase = int(time.time() // 7) % 3
        box = (int(h * 0.22), int(w * 0.65), int(h * 0.78), int(w * 0.35))
        if phase == 0:
            return []
        if phase == 1 and self.people:
            ids = list(self.people.keys())
            pid = ids[int(time.time() // 21) % len(ids)]
            return [self._face(pid, 0.31, box)]
        if phase == 1:
            return [{"box": box, "pid": "demo", "name": "Demo Student", "role": "Registered", "score": 88}]
        return [self._face(None, 0.78, box)]

    def _face(self, pid, dist, box):
        if pid is None:
            return {"box": box, "pid": None, "name": "Unknown", "role": None, "score": None}
        p = self.people[pid]
        score = None if dist is None else int(round(max(0.0, min(1.0, 1 - dist / (2 * self.tolerance))) * 100))
        return {"box": box, "pid": pid, "name": p["name"], "role": p["role"], "score": score}

    @staticmethod
    def _draw_cartoon(frame, box):
        t, r, b, l = box
        cx, cy = (l + r) // 2, (t + b) // 2
        rad = (b - t) // 2
        cv2.ellipse(frame, (cx, cy), (int(rad * 0.78), rad), 0, 0, 360, (150, 190, 225), -1)
        for dx in (-0.3, 0.3):
            cv2.circle(frame, (cx + int(rad * dx), cy - int(rad * 0.15)), max(4, rad // 12), (40, 30, 20), -1)
        cv2.ellipse(frame, (cx, cy + int(rad * 0.3)), (int(rad * 0.28), int(rad * 0.14)), 0, 0, 180, (40, 30, 20), 3)

    # ------------------------------------------------------- state, log, buzzer
    def _update(self, frame, faces):
        now = time.time()
        unknown = [f for f in faces if f["pid"] is None]
        known = [f for f in faces if f["pid"] is not None]
        area = lambda f: (f["box"][2] - f["box"][0]) * (f["box"][1] - f["box"][3])

        if faces:
            self._last_face_time = now
            primary = unknown[0] if unknown else max(known, key=area)
            status = "unknown" if unknown else "recognized"
        else:
            if now - self._last_face_time < 1.5 and self.state["status"] in ("recognized", "unknown"):
                return  # short gap, keep showing the last result
            primary, status = None, "no_face"

        with self.lock:
            if status != self.state["status"]:
                self.state["since"] = now
            self.state.update(status=status,
                              name=primary["name"] if primary else None,
                              role=primary["role"] if primary else None,
                              score=primary["score"] if primary else None)

        crop = None
        if primary and (now - self._face_stamp > 1.0 or self._face_stamp == 0):
            crop = self._crop(frame, primary["box"])
            self._face_stamp = now
            if crop:
                self.face_jpeg = crop
                self.face_version += 1
        if not primary:
            self._face_stamp = 0

        for f in known:  # recognized: log once per cooldown
            if now - self._last_seen.get(f["pid"], 0) > SEEN_COOLDOWN:
                self._last_seen[f["pid"]] = now
                self.stats["recognized"] += 1
                self._event("recognized", f"{f['name']} recognized", f["role"] or "Registered face",
                            crop or self._crop(frame, f["box"]))

        if unknown:  # unknown: buzzer + notification after a short confirmation delay
            if self._unknown_since is None:
                self._unknown_since = now
            if now - self._unknown_since >= UNKNOWN_SECONDS and now - self._last_alert >= ALERT_COOLDOWN:
                self._last_alert = now
                self.stats["unknown"] += 1
                detail = "Face is not registered."
                if self.buzzer_enabled:
                    self.stats["buzzer"] += 1
                    self.buzzer.alarm()
                    detail += " Buzzer sounded."
                else:
                    detail += " Buzzer is off."
                self._event("alert", "Unknown person detected", detail, crop or self._crop(frame, unknown[0]["box"]))
        else:
            self._unknown_since = None

    @staticmethod
    def _crop(frame, box):
        t, r, b, l = box
        h, w = frame.shape[:2]
        pad = int((b - t) * 0.25)
        face = frame[max(0, t - pad):min(h, b + pad), max(0, l - pad):min(w, r + pad)]
        if face.size == 0:
            return None
        face = cv2.resize(face, (240, int(240 * face.shape[0] / face.shape[1])))
        ok, buf = cv2.imencode(".jpg", face, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None

    def _annotate(self, frame, faces):
        out = frame.copy()
        for f in faces:
            t, r, b, l = f["box"]
            color = GREEN if f["pid"] else RED
            cv2.rectangle(out, (l, t), (r, b), color, 3)
            label = f["name"]
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(out, (l, b), (l + tw + 16, b + th + 14), color, -1)
            cv2.putText(out, label, (l + 8, b + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return out

    def _event(self, kind, title, detail, snap=None):
        self._seq += 1
        ev = {"id": self._seq, "ts": time.time(), "time": time.strftime("%H:%M:%S"),
              "kind": kind, "title": title, "detail": detail, "snap": bool(snap)}
        self.events.append(ev)
        if snap:
            self.snaps[ev["id"]] = snap
            if len(self.snaps) > 40:
                self.snaps.pop(next(iter(self.snaps)))

    # --------------------------------------------------------------- read-outs
    def get_frame_jpeg(self):
        if self.running and self.frame_jpeg:
            return self.frame_jpeg
        text = "Mini-Bot is asleep"
        if text not in self._placeholder:
            img = np.zeros((480, 640, 3), np.uint8)
            img[:] = (59, 35, 23)
            (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            cv2.putText(img, text, ((640 - tw) // 2, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (230, 220, 205), 2)
            self._placeholder[text] = cv2.imencode(".jpg", img)[1].tobytes()
        return self._placeholder[text]

    def snapshot(self):
        with self.lock:
            state = dict(self.state)
        return {
            "running": self.running,
            "mode": "demo" if self.demo else "live",
            "camera": self.camera.kind,
            "fps": round(self.fps, 1),
            "state": state,
            "tolerance": self.tolerance,
            "buzzer": {"enabled": self.buzzer_enabled, "active": self.buzzer.active,
                       "mock": self.buzzer.mock, "pin": self.buzzer.pin},
            "stats": self.stats,
            "people": len(self.people),
            "face_version": self.face_version,
            "events": list(self.events)[-30:][::-1],
        }
