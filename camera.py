"""Camera source. Tries the Pi Camera Module, then a USB/laptop webcam, then a synthetic demo feed."""
import os
import time

import cv2
import numpy as np


class Camera:
    def __init__(self, size=(640, 480)):
        self.size = size
        self.kind = "synthetic"
        self.picam = None
        self.cap = None

        try:  # Raspberry Pi Camera Module (CSI)
            from picamera2 import Picamera2
            self.picam = Picamera2()
            config = self.picam.create_video_configuration(main={"size": size, "format": "RGB888"})
            self.picam.configure(config)
            self.picam.start()
            self.kind = "pi-camera"
            return
        except Exception:
            self.picam = None

        try:  # USB webcam / laptop camera
            cap = cv2.VideoCapture(int(os.environ.get("CAMERA_INDEX", 0)))
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
                self.cap = cap
                self.kind = "webcam"
                return
            cap.release()
        except Exception:
            pass

    def read(self):
        """Return one BGR frame (numpy array) or None."""
        if self.picam is not None:
            return self.picam.capture_array()  # RGB888 on picamera2 is BGR order in memory
        if self.cap is not None:
            ok, frame = self.cap.read()
            return frame if ok else None
        return self._synthetic()

    def _synthetic(self):
        w, h = self.size
        frame = np.zeros((h, w, 3), np.uint8)
        frame[:] = (66, 46, 28)
        for x in range(0, w, 40):
            cv2.line(frame, (x, 0), (x, h), (78, 58, 38), 1)
        for y in range(0, h, 40):
            cv2.line(frame, (0, y), (w, y), (78, 58, 38), 1)
        cv2.putText(frame, "DEMO CAMERA", (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 190, 170), 2)
        cv2.putText(frame, time.strftime("%H:%M:%S"), (w - 120, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 190, 170), 1)
        time.sleep(0.04)
        return frame

    def close(self):
        if self.picam is not None:
            self.picam.stop()
        if self.cap is not None:
            self.cap.release()
