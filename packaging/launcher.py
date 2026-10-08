"""Entry point for the packaged app (PyInstaller)."""

from cable_desktop.mainwindow import main

if __name__ == "__main__":
    raise SystemExit(main())
