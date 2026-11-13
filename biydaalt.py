"""PlateWatch desktop entry point. Double-click run.bat on Windows."""
import multiprocessing
import argparse
import sys


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="PlateWatch desktop plate recognition")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--image", help="Open an image when the GUI starts")
    parser.add_argument("--camera", nargs="?", const="auto", help="Start camera preview; auto-detect by default")
    parser.add_argument("--verify-image", help="Check packaged YOLO/OCR and write a JSON report")
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    if args.verify_image:
        from platewatch.diagnostics import verify_image
        return verify_image(args.verify_image, args.report)
    from contextlib import nullcontext
    from platewatch.instance import desktop_instance
    from platewatch.gui import PlateWatchApp
    with nullcontext(True) if args.smoke_test else desktop_instance() as first:
        if not first:
            if args.camera is not None or args.image:
                from platewatch.settings import DATA_DIR, atomic_json, now_ub
                request = {"kind": "camera", "source": args.camera} if args.camera is not None else {"kind": "image", "source": [args.image]}
                request["at"] = now_ub().timestamp()
                atomic_json(DATA_DIR / "open_request.json", request)
            return 0
        app = PlateWatchApp()
        app.deiconify()
        app.lift()
        if args.image:
            app.after(200, lambda: app.start_source("image", [args.image]))
        elif args.camera is not None:
            app.camera_var.set("Авто" if args.camera.lower() == "auto" else args.camera)
            app.after(200, app.start_camera)
        if args.smoke_test:
            app.after(1600, app.close)
        app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
