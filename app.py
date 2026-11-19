"""Mini-Bot Face Recognition Dashboard (Flask).  Run:  python app.py  ->  http://localhost:5000"""
import time

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, render_template, request

from engine import Engine

app = Flask(__name__)
engine = Engine()


# ------------------------------------------------------------------- pages
@app.route("/")
def dashboard():
    return render_template("dashboard.html", active="dashboard")


@app.route("/people")
def people():
    return render_template("people.html", active="people")


@app.route("/how-it-works")
def how():
    return render_template("how.html", active="how")


# ------------------------------------------------------------- live camera
def mjpeg():
    while True:
        jpeg = engine.get_frame_jpeg()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.06)


@app.route("/video_feed")
def video_feed():
    return Response(mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/last_face.jpg")
def last_face():
    if not engine.face_jpeg:
        abort(404)
    return Response(engine.face_jpeg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.route("/api/event/<int:event_id>.jpg")
def event_snap(event_id):
    snap = engine.snaps.get(event_id)
    if not snap:
        abort(404)
    return Response(snap, mimetype="image/jpeg")


# --------------------------------------------------------------------- API
@app.route("/api/status")
def status():
    return jsonify(engine.snapshot())


@app.route("/api/control", methods=["POST"])
def control():
    action = (request.get_json(silent=True) or {}).get("action")
    if action == "start":
        engine.start()
    elif action == "stop":
        engine.stop()
    elif action == "test_buzzer":
        engine.buzzer.test()
    else:
        return jsonify(error="Unknown action"), 400
    return jsonify(ok=True)


@app.route("/api/settings", methods=["POST"])
def settings():
    data = request.get_json(silent=True) or {}
    if "tolerance" in data:
        engine.tolerance = min(0.7, max(0.3, float(data["tolerance"])))
    if "buzzer_enabled" in data:
        engine.buzzer_enabled = bool(data["buzzer_enabled"])
    return jsonify(ok=True)


@app.route("/api/people", methods=["GET"])
def list_people():
    return jsonify(engine.list_people())


@app.route("/api/people", methods=["POST"])
def add_person():
    name = (request.form.get("name") or "").strip()
    role = (request.form.get("role") or "").strip()
    if not name:
        return jsonify(error="Enter a name for this person."), 400

    if request.form.get("source") == "camera":
        if engine.last_raw is None:
            return jsonify(error="The camera has no frame yet. Press Start on the dashboard first."), 400
        image = engine.last_raw.copy()
    else:
        photo = request.files.get("photo")
        if not photo:
            return jsonify(error="Choose a photo or use the camera."), 400
        image = cv2.imdecode(np.frombuffer(photo.read(), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return jsonify(error="That file is not a readable image."), 400
    try:
        person = engine.add_person(name, role, image)
    except ValueError as exc:
        return jsonify(error=str(exc)), 422
    return jsonify(person), 201


@app.route("/api/people/<pid>", methods=["DELETE"])
def delete_person(pid):
    if not engine.remove_person(pid):
        abort(404)
    return jsonify(ok=True)


@app.route("/known_faces/<path:filename>")
def known_face_image(filename):
    from flask import send_from_directory
    from engine import KNOWN_DIR
    return send_from_directory(KNOWN_DIR, filename)


if __name__ == "__main__":
    # debug=False on purpose: the reloader would open the camera twice
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
