# Mini-Bot Face Desk

Web dashboard for the **Face Recognition with Raspberry Pi Camera** activity (Additional Task).

- Control and monitor the face recognition module from a browser
- Buzzer (GPIO 17) sounds when a face is not registered or not recognized
- Dashboard shows the captured face as Recognized or Not recognized
- Mini-Bot (the robot on the dashboard) is the actor: it smiles, frowns, shakes and sleeps
- "How it works" page has the AI algorithm flowchart, discussion, and answers to the activity questions

## Folder map

```
app.py            Flask routes (run this)
engine.py         face detection, matching, event log, buzzer logic
camera.py         Pi Camera / webcam / demo camera
buzzer.py         gpiozero buzzer (simulated on a PC)
templates/        dashboard.html, people.html, how.html
static/           css/style.css, js/app.js
known_faces/      enrolled photos (created automatically)
```

## Run it on your laptop (demo mode, 2 minutes)

1. Open this folder in VS Code (File > Open Folder).
2. Open a terminal (Ctrl + `) and run:

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        Mac/Linux:  source .venv/bin/activate
pip install flask numpy opencv-python
python app.py
```

3. Open http://localhost:5000

Without the `face_recognition` library the site runs in **demo mode**: it uses your webcam
(or a built-in demo camera) and simulates "nobody, registered person, stranger" so you can
test and screenshot the whole design.

## Run it for real on the Raspberry Pi

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv cmake build-essential
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install flask numpy face_recognition gpiozero
python app.py
```

Enable the camera in `sudo raspi-config` first. Then open `http://<pi-ip-address>:5000`
from a laptop or phone on the same Wi-Fi. Installing `face_recognition` builds dlib and can take
a long time on a Pi; that is normal.

### Buzzer wiring

| Buzzer | Raspberry Pi |
|--------|--------------|
| + (long leg) | GPIO 17 (physical pin 11) |
| - | GND (physical pin 9) |

Use a different pin with `BUZZER_PIN=27 python app.py`.

## How to use

1. Go to **People**, add your own face (upload a photo or use the live camera).
2. Go to **Dashboard**, press **Start**.
3. Face the camera: Mini-Bot smiles and the face card turns green.
4. Let someone not enrolled step in: Mini-Bot frowns, the card turns red, the buzzer beeps, and a notification appears.

Environment options: `DEMO=1` forces demo mode, `CAMERA_INDEX=1` picks another webcam.
