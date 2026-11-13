# PlateWatch 2.3.0 validation

The reported camera/import freeze was reproduced from the application log: at 10:55:51 on 2026-11-13, Pillow raised `MemoryError` while resizing a camera preview. The sole `poll()` callback scheduled its next invocation only on success, so it never ran again. Workers continued processing later selected files while the GUI stopped consuming frames, records and pending source changes.

The update loop now reschedules in `finally`. Preview rendering preserves the previous image on allocation failure and retries at a smaller resolution even when an imported photo has no further queued frames. Arrays are resized before Pillow/Tk conversion, preview dimensions are bounded, and a same-size Tk image is reused between camera frames. Pending history refreshes survive callback errors.

- All **39** automated tests passed with the project `.venv`, including injected preview `MemoryError`, an unrelated callback exception, image-only recovery without another frame, Tk image reuse, large-image preview and camera-to-image switching after an error.
- Real Windows/Tk end-to-end verification ran camera 0 (DSHOW, 640×480), deliberately failed the first camera preview allocation, observed automatic preview recovery, completed three actual YOLO/OCR camera inference cycles, then used the actual Windows file picker to import the user's Toyota photo.
- The imported photo produced **9638УЕН**, full-frame/crop JPEGs, CSV and JSON evidence. The recovered camera preview appeared after 2.121 seconds. `1113` still displayed Wednesday and the separately selected Friday remained allowed.
- Current check: `test_artifacts/native_import_verification.json`; screenshots: `native_import_gui.png` and `rules_1113_gui.png`.
- The existing EXE is the older 2.2.0 build; it does not contain this fix. Use the root `run.bat` / `camera.bat` to run 2.3.0. A future `build_exe.py` run takes its version directly from the Python package.

## Earlier 2.2.0 checks

- 35 automated tests passed using the project `.venv` Python 3.13.
- The user's exact Toyota photo, previously showing a `NoneType` error, was read as `9638УЕН` after retrying a wider plate crop and excluding the oval MGL emblem.
- The real Windows file picker was exercised through the new main-preview `+ Зураг` button. The Toyota image produced a saved image, crop, CSV row and metadata JSON.
- Typing `1113` now displays Wednesday as the configured restriction day. A separately selected Friday date remains an allowed date; this distinction was tested in both the GUI and rule engine.
- `test_artifacts/native_import_verification.json`, `toyota_photo_verification.json`, and `rules_1113_gui.png` record these checks.
- A physical-camera regression requested unavailable index 2 and automatically opened the Integrated Camera at index 0 through DSHOW. It delivered 291 preview frames, completed three inference cycles, stopped and reopened successfully.
- The user-selected real vehicle photo was processed after fixing an EasyOCR full-crop API error; the plate was read as `3892УНУ`.
- `camera.bat` and `biydaalt.py --camera` start the live camera directly. If the app is already open, a source request is sent to that window instead of opening a second instance.
- `run.bat --smoke-test` successfully opened and closed the updated GUI.
- Real camera index 0 opened with DSHOW at 640×480; the first preview arrived after 1.7 seconds. 304 preview frames and three inference cycles were observed without errors.
- Stopping the real camera released it; it was successfully reopened immediately afterward.
- A real GUI integration check started the physical camera, waited for AI inference, pressed the image import button, selected a fixture through the actual Windows file dialog, and switched from camera to image processing.
- Actual YOLO + Mongolian EasyOCR read `1234УБА` from the synthetic car fixture and saved full-frame JPEG, plate crop, JSON metadata, and CSV record in `test_artifacts/native_import_evidence`.
- `test_artifacts/camera_verification.json` and `test_artifacts/native_import_verification.json` record the physical camera and native dialog checks.
- `test_artifacts/python_verification_fixed.json` records a successful YOLO/OCR check after the memory fix.
- The tests cover button callbacks, cancelled dialogs, camera-to-image switching, Unicode filenames, TIFF, EXIF rotation, GUI responsiveness after AI errors, repeated readings, schedule/time boundaries, video import, and MP4 output.
- A Windows instance guard prevents repeated launches of this project from creating competing camera windows.

The live regression reproduced an OCR startup failure allocating 411,041,792 bytes for an unused VGG classifier. The updated code uses EasyOCR's documented `detector=False` and `recognize()` API on the YOLO crop, avoiding the second CRAFT/VGG detector. OpenCV finds prominent text rows when needed. Image/camera preview starts before AI loading, and errors are displayed in the GUI without blocking source changes.

PyInstaller successfully rebuilt `dist/PlateWatch/PlateWatch.exe` from the final 2.2.0 source, with Python, AI dependencies and local model weights. The resulting folder is approximately 672 MB. A launch test of this exact build failed with Windows error 4551: "An Application Control policy has blocked this file". Therefore the packaged GUI/AI runtime is not verified on this PC. The result is recorded in `test_artifacts/exe_verification_2_2.json`. No security policy was changed. The root `run.bat` is independently tested and the 2.2.0 Python GUI remains available.

No labelled Mongolian dataset was supplied, so no Mongolian fine-tuning or real-world recognition-accuracy evaluation was performed. The physical-camera checks establish capture, inference and release; the synthetic fixture establishes an actual recognition and evidence-saving path. They do not establish road-camera accuracy.
