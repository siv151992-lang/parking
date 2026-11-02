# Camera Configuration

## Adding a real ANPR / IP camera

1. Install the AI dependencies on the server that processes video: `pip install -r backend/requirements-ai.txt`. Without them, real cameras still stream video but show *ANPR engine unavailable*.
2. Go to **Camera Management → Add camera → Real IP camera (RTSP)**.
3. Fill in:
   * **Camera ID** (unique, e.g. `CAM-EN-03`), **Name**, **Location**.
   * **Direction**: `ENTRY` or `EXIT`. This decides whether a recognised vehicle opens or closes a session.
   * **IP address, RTSP port (554), ONVIF port (usually 80)**.
   * **Username / Password**. They are injected into the RTSP URL automatically, so keep the URL without credentials.
   * **RTSP URL**. Click **Get RTSP via ONVIF** to fetch it from the camera, or type it in:

   | Brand | Typical main-stream URL |
   |---|---|
   | Hikvision | `rtsp://IP:554/Streaming/Channels/101` |
   | Dahua / Amcrest | `rtsp://IP:554/cam/realmonitor?channel=1&subtype=0` |
   | Axis | `rtsp://IP/axis-media/media.amp` |
   | Uniview | `rtsp://IP:554/unicast/c1/s0/live` |
   | Generic ONVIF | use *Get RTSP via ONVIF* |

4. Click **Test connection**. A snapshot and the stream resolution confirm the URL works.
5. Set **Cooldown** (default 60 s) and **Min. plate confidence** (default 0.6).
6. Adjust the **detection zone**: a polygon in normalised 0–1 coordinates, plus the **trigger line**. Draw the zone tightly around the lane in front of the camera, and put the line where plates are largest and sharpest. The live view draws both, so you can check them.
7. Save. A worker thread connects immediately. The status changes to `ONLINE`, and the stream appears in **Live Camera Monitoring**.

**Discover ONVIF** scans the local subnet (WS-Discovery multicast) and pre-fills new cameras.

## Recommended camera setup for ANPR

* Mount the camera 1.5–3 m high with less than 30° horizontal angle to the plate. Plate width in the image should be at least 130 px.
* Shutter 1/1000 s or faster, and IR illumination at night. Avoid backlight from the lane exit.
* 25 fps H.264 main stream at 1080p. Raise `PROCESS_EVERY_N_FRAMES` on weaker CPUs.
* Use a dedicated licence-plate YOLO model for best accuracy: set `YOLO_PLATE_MODEL=/path/plate.pt` in `.env`. Without one, OpenCV morphology and PaddleOCR text detection locate the plate.
* For country-specific validation, set the `plate_regex` setting. Example for India: `[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}`.

## Reliability

* RTSP runs over TCP. If no frames arrive for 10 s the camera is marked `OFFLINE`, a **Camera disconnected** alert is raised, and the worker reconnects with exponential back-off (2 s → 60 s). On success, a **Camera connection restored** alert follows.
* Each camera runs in its own thread, so one failing camera never affects the others.
* Frames are always the newest available. The grabber thread drops stale frames.
* Changes to the URL, credentials, direction, or enabled state restart the worker automatically. Zone and cooldown changes apply within 5 s without a restart.

## Simulation mode (no hardware)

Choose **Simulated camera** when adding a camera. The simulator renders a gate lane with vehicles carrying readable plates, and feeds the *same* tracker and counting pipeline. It includes OCR confusions, unreadable plates, vehicles that wait at a barrier (to test duplicate prevention), and, with `SIM_DISCONNECT_PROBABILITY` > 0, random stream drops (to test reconnect alerts).

* Exit simulators mostly pick vehicles that are currently parked (simulated sessions), so entries and exits balance.
* `SIM_USE_REAL_ANPR=true` runs YOLO and PaddleOCR on the rendered frames instead of using ground truth.
* **Inject test vehicle** (Live Camera Monitoring) pushes one pass with a chosen plate, type and confidence through any camera's pipeline.
* A recorded video file path can be used as the RTSP URL of a *real* camera to test the full YOLO/OCR pipeline on real footage.

Everything simulated is labelled **SIM** in the UI, watermarked on video, flagged in the database, and can be excluded from reports.
