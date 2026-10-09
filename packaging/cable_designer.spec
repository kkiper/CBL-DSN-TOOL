# PyInstaller spec for Cable Designer.  Build from the repository root:
#     pyinstaller packaging/cable_designer.spec --noconfirm
# Windows/Linux: dist/CableDesigner(.exe), one file.  macOS: dist/CableDesigner.app
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from cable_desktop import __version__  # noqa: E402

datas = [(str(p), "samples") for p in (ROOT / "samples").glob("*.csv")]
datas += [(str(p), "libraries") for p in (ROOT / "libraries").glob("*.csv")]
datas += [(str(ROOT / "packaging" / "icon.png"), "packaging")]
datas += collect_data_files("reportlab")          # fonts and metrics used for PDF output

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["PySide6.QtSvg", "PySide6.QtSvgWidgets"],
    excludes=["streamlit", "altair", "tornado", "pyarrow", "matplotlib", "ezdxf", "pytest", "IPython", "tkinter",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CableDesigner", console=False,
              icon=str(ROOT / "packaging" / "icon_1024.png"))
    coll = COLLECT(exe, a.binaries, a.datas, name="CableDesigner")
    app = BUNDLE(
        coll,
        name="CableDesigner.app",
        icon=str(ROOT / "packaging" / "icon_1024.png"),
        bundle_identifier="com.cabledesigner.app",
        version=__version__,
        info_plist={
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Cable Designer project",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["com.cabledesigner.cbl"],
                "LSHandlerRank": "Owner",
            }],
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "com.cabledesigner.cbl",
                "UTTypeDescription": "Cable Designer project",
                "UTTypeConformsTo": ["public.json"],
                "UTTypeTagSpecification": {"public.filename-extension": ["cbl"]},
            }],
        },
    )
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="CableDesigner", console=False,
              icon=str(ROOT / "packaging" / "icon.ico"), upx=False)
