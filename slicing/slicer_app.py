"""PySide6 + QML front end for the four-window slicer.

    python slicing/slicer_app.py [file]

Pick the cutline layer and width, watch the four windows update over the wafer,
then run. All slicing logic lives in `slicer_preview.py` and `run_splitter.py`;
this file is presentation and plumbing only.

Named datasets are kept in `slicing/.ui_datasets.json`, the same shape the
profilometer UI uses for its sample library: `{name: {settings...}}`.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import PySide6

# The QML plugins live in PySide6/qml/... and link against the Qt6*.dll files in
# the package root. Windows will not search that root for a DLL loaded from a
# nested directory, so without this the QtQuick.Controls style plugins fail with
# "The specified module could not be found". Must happen before Qt loads plugins.
_PYSIDE_DIR = str(Path(PySide6.__file__).parent)
os.environ["PATH"] = _PYSIDE_DIR + os.pathsep + os.environ.get("PATH", "")
try:
    os.add_dll_directory(_PYSIDE_DIR)
except OSError:
    pass

from PySide6.QtCore import (Property, QAbstractListModel, QByteArray, QModelIndex,  # noqa: E402
                            QObject, QPointF, QProcess, QRectF, Qt, QThread, QTimer,
                            QUrl, Signal, Slot)
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter,  # noqa: E402
                           QPainterPath, QPen)
from PySide6.QtQml import QmlElement, QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickPaintedItem  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import slicer_preview  # noqa: E402
from make_figures import WAFER_RADIUS, wafer_outline  # noqa: E402
from run_splitter import inspect_layers  # noqa: E402

QML_IMPORT_NAME = "Slicer"
QML_IMPORT_MAJOR_VERSION = 1

RUN_SPLITTER = HERE / "run_splitter.py"
DATASETS_JSON = HERE / ".ui_datasets.json"

STATION_COLORS = {
    "P1": "#4cc2ff",
    "P2": "#ffb951",
    "P3": "#c39bf0",
    "P4": "#6ccb5f",
}
CUT_COLOR = "#f2f2f2"
ANCHOR_COLOR = "#ff99a4"
SEAM_COLOR = "#ff6b6b"
GUIDE_COLOR = "#7a7a7a"
TEXT_2 = "#c5c5c5"
TEXT_3 = "#8a8a8a"
SURFACE = "#191919"
FACE = "Segoe UI Variable Text"

# Every field the UI remembers per dataset.
DATASET_FIELDS = ("input", "output", "layer", "cutWidth", "widthMode", "clipMode",
                  "globalX", "globalY", "allowOutside",
                  "extension", "stationOffsets", "stitchUm", "edgeBead",
                  "mode", "scoreDiameter", "scoreShape")


# --------------------------------------------------------------------- models


class LayerModel(QAbstractListModel):
    """Layers found in the source file, for the combo box."""

    SelectorRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    DetailRole = Qt.UserRole + 3

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    def roleNames(self) -> dict:
        return {
            self.SelectorRole: QByteArray(b"selector"),
            self.LabelRole: QByteArray(b"label"),
            self.DetailRole: QByteArray(b"detail"),
        }

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        return {
            self.SelectorRole: row["selector"],
            self.LabelRole: row["label"],
            self.DetailRole: row["detail"],
        }.get(role)

    def set_layers(self, entries) -> None:
        self.beginResetModel()
        self._rows = []
        for entry in entries:
            bits = []
            if entry.polygons:
                bits.append(f"{entry.polygons} polygon{'s' if entry.polygons != 1 else ''}")
            if entry.paths:
                widths = ", ".join(f"{w:g}" for w in entry.widths_um[:3])
                bits.append(f"{entry.paths} path{'s' if entry.paths != 1 else ''} at {widths} um")
            if not bits:
                bits.append("empty")
            self._rows.append({
                "selector": entry.selector,
                "label": entry.name or f"{entry.layer}/{entry.datatype}",
                "detail": f"{'  ·  '.join(bits)}   ·   {entry.area_mm2:.3f} mm²",
            })
        self.endResetModel()

    def selector_at(self, row: int) -> str:
        return self._rows[row]["selector"] if 0 <= row < len(self._rows) else ""

    def row_of(self, selector: str) -> int:
        for index, row in enumerate(self._rows):
            if row["selector"] == selector:
                return index
        return -1

    @staticmethod
    def best_row(entries) -> int:
        """The layer with the most drawn area is the cutline layer in practice."""
        if not entries:
            return -1
        areas = [e.area_mm2 for e in entries]
        return areas.index(max(areas))


# ------------------------------------------------------------------- painting


@dataclass
class Viewport:
    """Maps millimetres to item pixels, y flipped, aspect preserved."""

    scale: float
    offset_x: float
    offset_y: float

    def point(self, x_mm: float, y_mm: float) -> QPointF:
        return QPointF(self.offset_x + x_mm * self.scale, self.offset_y - y_mm * self.scale)

    def rect(self, left: float, bottom: float, right: float, top: float) -> QRectF:
        return QRectF(self.point(left, top), self.point(right, bottom))


@QmlElement
class PreviewItem(QQuickPaintedItem):
    """The wafer with its four windows, or the four sliced jobs side by side."""

    modeChanged = Signal()
    captionChanged = Signal()
    waferGuideChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRenderTarget(QQuickPaintedItem.FramebufferObject)
        self.setAntialiasing(True)
        self._preview: slicer_preview.Preview | None = None
        self._mode = "wafer"
        self._wafer_guide = True
        self._caption = ""

    def _get_mode(self) -> str:
        return self._mode

    def _set_mode(self, value: str) -> None:
        if value != self._mode:
            self._mode = value
            self.modeChanged.emit()
            self.update()

    mode = Property(str, _get_mode, _set_mode, notify=modeChanged)

    def _get_guide(self) -> bool:
        return self._wafer_guide

    def _set_guide(self, value: bool) -> None:
        if value != self._wafer_guide:
            self._wafer_guide = value
            self.waferGuideChanged.emit()
            self.update()

    waferGuide = Property(bool, _get_guide, _set_guide, notify=waferGuideChanged)

    def _get_caption(self) -> str:
        return self._caption

    caption = Property(str, _get_caption, notify=captionChanged)

    def set_preview(self, preview) -> None:
        self._preview = preview
        if preview is None:
            self._caption = ""
        elif getattr(preview, "run_mode", "four_windows") == "center_pass":
            self._caption = (
                f"{preview.source_area_mm2:.3f} mm² of cut geometry   ·   "
                f"{preview.score_shape} score {preview.score_diameter_mm:.3f} mm"
                + (f"   ·   {preview.dropped_area_mm2:.3f} mm² outside the score"
                   if preview.dropped_area_mm2 > 0 else "")
            )
        else:
            self._caption = (
                f"{preview.source_area_mm2:.3f} mm² of cut geometry   ·   "
                f"field {preview.field_mm:.3f} mm   ·   stitch {preview.stitch_mm:.3f} mm"
                + (f"   ·   {preview.dropped_area_mm2:.3f} mm² outside the windows"
                   if preview.dropped_area_mm2 > 0 else "")
            )
        self.captionChanged.emit()
        self.update()

    # -------------------------------------------------------------- helpers

    def _font(self, painter: QPainter, size: int, bold: bool = False) -> None:
        font = QFont(FACE)
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)

    def _path(self, polys, view: Viewport) -> QPainterPath:
        path = QPainterPath()
        for poly in polys:
            if len(poly) < 2:
                continue
            path.moveTo(view.point(*poly[0]))
            for x, y in poly[1:]:
                path.lineTo(view.point(x, y))
            path.closeSubpath()
        return path

    def _ink(self, painter: QPainter, path: QPainterPath, colour: str,
             width: float = 1.1) -> None:
        """A 50 um cut is far under a pixel, so stroke as well as fill."""
        painter.setBrush(QColor(colour))
        pen = QPen(QColor(colour))
        pen.setWidthF(width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPath(path)

    def _outline(self, painter: QPainter, polys, view: Viewport, colour: str,
                 width: float, dashed: bool = False) -> None:
        pen = QPen(QColor(colour))
        pen.setWidthF(width)
        pen.setCosmetic(True)
        if dashed:
            pen.setDashPattern([5, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._path(polys, view))

    # ---------------------------------------------------------------- paint

    def paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.fillRect(rect, QColor(SURFACE))
        if self._preview is None:
            self._font(painter, 13)
            painter.setPen(QPen(QColor(TEXT_3)))
            painter.drawText(rect, Qt.AlignCenter,
                             "Choose a source file to see the slice preview")
            return
        if getattr(self._preview, "run_mode", "four_windows") == "center_pass":
            self._draw_center_pass(painter, rect)
        elif self._mode == "sliced":
            self._draw_sliced(painter, rect)
        else:
            self._draw_wafer(painter, rect)

    # The wafer with the four windows over it, the view that reads at a glance.
    def _draw_wafer(self, painter: QPainter, rect: QRectF) -> None:
        preview = self._preview
        reach = max(abs(v) for tile in preview.tiles for v in tile.clip_mm)
        # Labels sit in the four outer corners, so reserve room for them.
        span = reach * 1.06
        usable = min(rect.width(), rect.height()) - 24
        view = Viewport(max(usable, 40.0) / (2 * span), rect.center().x(), rect.center().y())

        if self._wafer_guide:
            self._outline(painter, [wafer_outline(WAFER_RADIUS)], view, GUIDE_COLOR, 1.4)
            bead = getattr(preview, "edge_bead_mm", 0.0) or 0.0
            if bead > 0:
                self._outline(painter,
                              [wafer_outline(WAFER_RADIUS - bead, bead, bead)],
                              view, GUIDE_COLOR, 1.0, dashed=True)

        for tile in preview.tiles:
            colour = QColor(STATION_COLORS.get(tile.folder, "#8a8a8a"))
            painter.setBrush(QColor(colour.red(), colour.green(), colour.blue(), 20))
            pen = QPen(colour)
            pen.setWidthF(1.6)
            painter.setPen(pen)
            painter.drawRect(view.rect(*tile.clip_mm))

        self._ink(painter, self._path(preview.source_cuts_mm, view), CUT_COLOR, 1.0)

        pen = QPen(QColor(SEAM_COLOR))
        pen.setWidthF(1.0)
        pen.setDashPattern([4, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(view.point(-reach, 0), view.point(reach, 0))
        painter.drawLine(view.point(0, -reach), view.point(0, reach))

        self._draw_corner_labels(painter, preview, view, reach)

    def _draw_corner_labels(self, painter, preview, view: Viewport, reach: float) -> None:
        """One label per station, tucked into the outer corner of its window.

        The wafer is round and the windows are square, so those four corners are
        the only large empty areas; putting the labels there is what keeps them
        off the geometry and off each other.
        """
        for tile in preview.tiles:
            left, bottom, right, top = tile.clip_mm
            on_right = tile.field_center_mm[0] > 0
            on_top = tile.field_center_mm[1] > 0
            corner = view.point(right if on_right else left, top if on_top else bottom)

            inset = 10.0
            width = 190.0
            line = 17.0
            block = line * 3
            x = corner.x() - width - inset if on_right else corner.x() + inset
            y = corner.y() + inset if on_top else corner.y() - inset - block
            align = (Qt.AlignRight if on_right else Qt.AlignLeft) | Qt.AlignVCenter
            colour = STATION_COLORS.get(tile.folder, "#8a8a8a")

            self._font(painter, 15, bold=True)
            painter.setPen(QPen(QColor(colour)))
            painter.drawText(QRectF(x, y, width, line), align, tile.folder)

            self._font(painter, 12)
            painter.setPen(QPen(QColor(TEXT_2)))
            painter.drawText(QRectF(x, y + line, width, line), align,
                             f"jig {tile.station.replace('_', '-')}")
            painter.setPen(QPen(QColor(TEXT_3)))
            painter.drawText(QRectF(x, y + line * 2, width, line), align,
                             f"exposes {tile.exposed.replace('_', '-')}")

    # A single centered score job: the wafer with the score boundary over it.
    def _draw_center_pass(self, painter: QPainter, rect: QRectF) -> None:
        preview = self._preview
        radius = max(preview.score_diameter_mm / 2.0, 1.0)
        span = max(WAFER_RADIUS, radius) * 1.12
        usable = min(rect.width(), rect.height()) - 24
        view = Viewport(max(usable, 40.0) / (2 * span), rect.center().x(), rect.center().y())

        if self._wafer_guide:
            self._outline(painter, [wafer_outline(WAFER_RADIUS)], view, GUIDE_COLOR, 1.4)
            bead = getattr(preview, "edge_bead_mm", 0.0) or 0.0
            if bead > 0:
                self._outline(painter, [wafer_outline(WAFER_RADIUS - bead, bead, bead)],
                              view, GUIDE_COLOR, 1.0, dashed=True)

        # Whole source faint, then the kept (scored) geometry bright.
        self._ink(painter, self._path(preview.source_cuts_mm, view), TEXT_3, 0.8)

        pen = QPen(QColor(SEAM_COLOR))
        pen.setWidthF(1.4)
        pen.setCosmetic(True)
        pen.setDashPattern([5, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if preview.score_shape == "square":
            painter.drawRect(view.rect(-radius, -radius, radius, radius))
        else:
            center = view.point(0.0, 0.0)
            painter.drawEllipse(center, radius * view.scale, radius * view.scale)

        self._ink(painter, self._path(preview.center_cuts_mm, view), CUT_COLOR, 1.1)

    # The four jobs as the laser will see them, each centred on its own origin.
    def _draw_sliced(self, painter: QPainter, rect: QRectF) -> None:
        preview = self._preview
        half = preview.half_mm
        grid = {"P1": (0, 0), "P2": (1, 0), "P3": (1, 1), "P4": (0, 1)}
        gap, caption = 16.0, 40.0
        side = max(min((rect.width() - gap * 3) / 2,
                       (rect.height() - gap * 3 - caption * 2) / 2), 40.0)
        origin_x = (rect.width() - (side * 2 + gap)) / 2
        origin_y = (rect.height() - (side * 2 + caption * 2 + gap)) / 2

        for tile in preview.tiles:
            column, row = grid.get(tile.folder, (0, 0))
            cell = QRectF(origin_x + column * (side + gap),
                          origin_y + row * (side + caption + gap), side, side)
            self._draw_tile(painter, cell, tile, half, caption)

    def _draw_tile(self, painter: QPainter, cell: QRectF, tile, half: float,
                   caption: float) -> None:
        colour = STATION_COLORS.get(tile.folder, "#8a8a8a")

        painter.setBrush(QColor("#141414"))
        pen = QPen(QColor("#303030"))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(cell, 6, 6)

        view = Viewport((cell.width() - 26) / (2 * half), cell.center().x(), cell.center().y())

        pen = QPen(QColor(colour))
        pen.setWidthF(1.4)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(view.rect(-half, -half, half, half))

        if tile.cuts_mm:
            self._ink(painter, self._path(tile.cuts_mm, view), CUT_COLOR, 1.0)
        else:
            self._font(painter, 12)
            painter.setPen(QPen(QColor(ANCHOR_COLOR)))
            painter.drawText(cell, Qt.AlignCenter, "no cut geometry")

        pen = QPen(QColor("#454545"))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        reach = half * 0.1
        painter.drawLine(view.point(-reach, 0), view.point(reach, 0))
        painter.drawLine(view.point(0, -reach), view.point(0, reach))

        # Two caption lines, each split into halves so nothing can collide.
        half_width = cell.width() / 2 - 6
        rows = (
            (tile.folder, f"{tile.polygon_count} poly", colour, TEXT_3, 13, True),
            (f"jig {tile.station.replace('_', '-')}",
             f"{tile.area_mm2:.3f} mm²", TEXT_2, TEXT_3, 12, False),
        )
        for index, (left_text, right_text, left_colour, right_colour, size, bold) in enumerate(rows):
            top = cell.bottom() + 6 + index * 17
            self._font(painter, size, bold=bold)
            metrics = painter.fontMetrics()
            painter.setPen(QPen(QColor(left_colour)))
            painter.drawText(QRectF(cell.left(), top, half_width, 16),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             metrics.elidedText(left_text, Qt.ElideRight, int(half_width)))
            painter.setPen(QPen(QColor(right_colour)))
            painter.drawText(QRectF(cell.center().x() + 6, top, half_width, 16),
                             Qt.AlignRight | Qt.AlignVCenter,
                             metrics.elidedText(right_text, Qt.ElideRight, int(half_width)))


# -------------------------------------------------------------------- backend


class PreviewWorker(QThread):
    done = Signal(object, str)

    def __init__(self, params: dict) -> None:
        super().__init__()
        self._params = params

    def run(self) -> None:
        try:
            self.done.emit(slicer_preview.build_preview(**self._params), "")
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self.done.emit(None, str(exc))


class Bridge(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    logAppended = Signal(str)
    logCleared = Signal()
    previewReady = Signal()
    layersChanged = Signal()
    datasetsChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._status = "Choose a source file, or load a saved dataset."
        self._busy = False
        self._layers = LayerModel()
        self._entries: list = []
        self._item: PreviewItem | None = None
        self._worker: PreviewWorker | None = None
        self._process: QProcess | None = None
        self._notes: list[str] = []
        self._datasets: dict[str, dict] = self._read_datasets()

    # ------------------------------------------------------------ datasets

    def _read_datasets(self) -> dict:
        if DATASETS_JSON.exists():
            try:
                loaded = json.loads(DATASETS_JSON.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except (OSError, ValueError):
                pass
        return {}

    def _write_datasets(self) -> None:
        try:
            DATASETS_JSON.write_text(json.dumps(self._datasets, indent=2, sort_keys=True),
                                     encoding="utf-8")
        except OSError as exc:
            self._set_status(f"Could not save datasets: {exc}")

    def _get_dataset_names(self) -> list:
        return sorted(self._datasets)

    datasetNames = Property(list, _get_dataset_names, notify=datasetsChanged)

    @Slot(str, "QVariantMap")
    def saveDataset(self, name: str, params) -> None:
        name = name.strip()
        if not name:
            self._set_status("Give the dataset a name first.")
            return
        self._datasets[name] = {key: params.get(key) for key in DATASET_FIELDS}
        self._write_datasets()
        self.datasetsChanged.emit()
        self._set_status(f"Saved dataset '{name}'.")

    @Slot(str, result="QVariantMap")
    def loadDataset(self, name: str) -> dict:
        stored = self._datasets.get(name)
        if not stored:
            return {"ok": False}
        result = dict(stored)
        result["ok"] = True
        source = Path(str(stored.get("input") or ""))
        if source.is_file():
            try:
                self._entries = inspect_layers(source)
                self._layers.set_layers(self._entries)
                self.layersChanged.emit()
                result["layerRow"] = self._layers.row_of(str(stored.get("layer") or ""))
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"Dataset '{name}': could not read source: {exc}")
                result["layerRow"] = -1
        else:
            result["layerRow"] = -1
            self._set_status(f"Dataset '{name}': source file is missing.")
        return result

    @Slot(str)
    def deleteDataset(self, name: str) -> None:
        if self._datasets.pop(name, None) is not None:
            self._write_datasets()
            self.datasetsChanged.emit()
            self._set_status(f"Deleted dataset '{name}'.")

    # ---------------------------------------------------------- properties

    def _get_status(self) -> str:
        return self._status

    status = Property(str, _get_status, notify=statusChanged)

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    def _get_busy(self) -> bool:
        return self._busy

    busy = Property(bool, _get_busy, notify=busyChanged)

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit()

    def _get_geometry_summary(self) -> str:
        """Read the field geometry off the splitter so the header cannot drift."""
        ns = slicer_preview.splitter_namespace()
        return (
            f"{ns['QUALIFIED_FIELD_SIZE_UM'] / 1000.0:g} mm field"
            f"  ·  centers ±{ns['WINDOW_CENTER_X_UM'] / 1000.0:g} mm"
            f"  ·  stitch {ns['STITCH_OVERLAP_UM'] / 1000.0:g} mm"
            f"  ·  window {ns['partition_window_size_um'](ns['STITCH_OVERLAP_UM']) / 1000.0:g} mm"
        )

    geometrySummary = Property(str, _get_geometry_summary, constant=True)

    def _get_default_stitch(self) -> float:
        return float(slicer_preview.splitter_namespace()["STITCH_OVERLAP_UM"])

    defaultStitchUm = Property(float, _get_default_stitch, constant=True)

    def _get_max_stitch(self) -> float:
        """Past this a window would reach outside the declared field, and the
        splitter refuses. Derived, not hardcoded."""
        ns = slicer_preview.splitter_namespace()
        return float(ns["QUALIFIED_FIELD_SIZE_UM"] - 2.0 * ns["WINDOW_CENTER_X_UM"])

    maxStitchUm = Property(float, _get_max_stitch, constant=True)

    @staticmethod
    def _calibrated_offset() -> tuple[float, float]:
        """The global calibration baked into the splitter. The UI offset adds to
        it, and per-station nudges add on top of that, so the calibration is the
        hidden baseline beneath every adjustment."""
        ns = slicer_preview.splitter_namespace()
        return float(ns["GLOBAL_X_OFFSET_UM"]), float(ns["GLOBAL_Y_OFFSET_UM"])

    def _get_cal_x(self) -> float:
        return self._calibrated_offset()[0]

    calibratedOffsetXUm = Property(float, _get_cal_x, constant=True)

    def _get_cal_y(self) -> float:
        return self._calibrated_offset()[1]

    calibratedOffsetYUm = Property(float, _get_cal_y, constant=True)

    def _get_layers(self) -> QObject:
        return self._layers

    layerModel = Property(QObject, _get_layers, notify=layersChanged)

    def _get_notes(self) -> list:
        return self._notes

    notes = Property(list, _get_notes, notify=previewReady)

    # --------------------------------------------------------------- slots

    @Slot(QObject)
    def attachPreview(self, item) -> None:
        self._item = item

    @Slot(QUrl, result="QVariantMap")
    def loadFile(self, url: QUrl) -> dict:
        path = Path(url.toLocalFile() if url.isLocalFile() else url.toString())
        return self.loadPath(str(path))

    @Slot(str, result="QVariantMap")
    def loadPath(self, text: str) -> dict:
        path = Path(text)
        if not path.is_file():
            self._set_status(f"Not a file: {path}")
            return {"ok": False}
        try:
            self._entries = inspect_layers(path)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not read: {exc}")
            return {"ok": False}
        self._layers.set_layers(self._entries)
        self.layersChanged.emit()
        self._set_status(f"{len(self._entries)} layer(s) in {path.name}")
        return {
            "ok": True,
            "path": str(path),
            "layerRow": LayerModel.best_row(self._entries),
            "suggestedOutput": f"{path.stem}_four_windows",
        }

    @Slot(int, result=str)
    def selectorAt(self, row: int) -> str:
        return self._layers.selector_at(row)

    @Slot("QVariantMap")
    def refreshPreview(self, params) -> None:
        path = Path(str(params.get("input", "")))
        if not path.is_file():
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        cal_x, cal_y = self._calibrated_offset()
        self._worker = PreviewWorker({
            "input_path": path,
            "layer_spec": str(params.get("layer", "")),
            "cut_width_um": float(params.get("cutWidth", 50.0)),
            "width_mode": str(params.get("widthMode", "cap")),
            "clip_mode": str(params.get("clipMode", "partition")),
            "global_x_um": cal_x + float(params.get("globalX", 0.0) or 0.0),
            "global_y_um": cal_y + float(params.get("globalY", 0.0) or 0.0),
            "window_offsets": self._offsets_from(params),
            "stitch_um": self._stitch_from(params),
            "edge_bead_mm": float(params.get("edgeBead", 0.0) or 0.0),
            "run_mode": "center_pass" if str(params.get("mode", "")) == "center-pass" else "four_windows",
            "score_diameter_um": float(params.get("scoreDiameter", 75.0) or 75.0) * 1000.0,
            "score_shape": str(params.get("scoreShape", "circle")),
        })
        self._worker.done.connect(self._preview_done)
        self._worker.start()

    def _stitch_from(self, params) -> float:
        """Blank or unset means the splitter's own default."""
        raw = str(params.get("stitchUm", "")).strip()
        if not raw:
            return self._get_default_stitch()
        try:
            return float(raw)
        except ValueError:
            return self._get_default_stitch()

    @staticmethod
    def _offsets_from(params) -> dict:
        """Pull the per-station nudges out of the QML params map."""
        stations = ("P1", "P2", "P3", "P4")
        raw = params.get("stationOffsets") or {}
        return {label: (float((raw.get(label) or {}).get("x", 0.0) or 0.0),
                        float((raw.get(label) or {}).get("y", 0.0) or 0.0))
                for label in stations}

    def _preview_done(self, preview, error: str) -> None:
        self._set_busy(False)
        if error:
            self._notes = [error]
            self._set_status("Preview failed.")
        else:
            self._notes = list(preview.notes)
            self._set_status("   ".join(
                f"{tile.folder} {tile.polygon_count}" for tile in preview.tiles))
        if self._item is not None:
            self._item.set_preview(preview)
        self.previewReady.emit()

    @Slot("QVariantMap")
    def runSlicer(self, params) -> None:
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            return
        path = Path(str(params.get("input", "")))
        if not path.is_file():
            self._set_status("Choose a source file first.")
            return

        cal_x, cal_y = self._calibrated_offset()
        arguments = [
            str(RUN_SPLITTER),
            "--input", str(path),
            "--cut-width", str(params.get("cutWidth", 50.0)),
            "--width-mode", str(params.get("widthMode", "cap")),
            "--clip-mode", str(params.get("clipMode", "partition")),
            "--global-x", str(cal_x + float(params.get("globalX", 0.0) or 0.0)),
            "--global-y", str(cal_y + float(params.get("globalY", 0.0) or 0.0)),
            "--edge-bead", str(params.get("edgeBead", 0.0) or 0.0),
            "--extension", str(params.get("extension", ".dxf")),
            "--mode", str(params.get("mode", "four-window")),
            "--score-diameter", str(float(params.get("scoreDiameter", 75.0) or 75.0) * 1000.0),
            "--score-shape", str(params.get("scoreShape", "circle")),
        ]
        output = str(params.get("output", "")).strip()
        if output:
            # A bare name lands under the repo's output/ folder; a full path wins.
            if not os.path.isabs(output):
                output = str(REPO_ROOT / "output" / output)
            arguments += ["--output", output]
        layer = str(params.get("layer", "")).strip()
        if layer:
            arguments += ["--layer", layer]
        if bool(params.get("allowOutside", False)):
            arguments.append("--allow-outside")
        arguments += ["--stitch", f"{self._stitch_from(params):g}"]
        for label, (x, y) in self._offsets_from(params).items():
            if x or y:
                arguments += ["--offset", f"{label}={x:g},{y:g}"]

        self.logCleared.emit()
        self.logAppended.emit("> " + " ".join(arguments[1:]) + "\n\n")
        self._set_busy(True)
        self._set_status("Slicing...")

        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(REPO_ROOT))
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._drain_process)
        self._process.finished.connect(self._process_finished)
        self._process.start(sys.executable, arguments)

    def _drain_process(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        if chunk:
            self.logAppended.emit(chunk)

    def _process_finished(self, code: int, _status) -> None:
        self._set_busy(False)
        if code == 0:
            self.logAppended.emit("\nDone.\n")
            self._set_status("Finished.")
        else:
            self.logAppended.emit(f"\nFailed with exit code {code}.\n")
            self._set_status("Failed. See the log.")
        self._process = None


def main() -> int:
    QGuiApplication.setApplicationName("UV Laser Singulation")
    QGuiApplication.setOrganizationName("UV-Laser-Singulation")

    # Qt's own Windows 11 style, so the controls are the real thing rather than an
    # imitation. Override with SLICER_QML_STYLE=Basic if it ever misbehaves.
    QQuickStyle.setStyle(os.environ.get("SLICER_QML_STYLE", "FluentWinUI3"))

    app = QGuiApplication(sys.argv)
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)

    engine = QQmlApplicationEngine()
    bridge = Bridge()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.addImportPath(str(HERE / "qml"))
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        print("Failed to load the QML interface.", file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if positional and Path(positional[0]).is_file():
        window.setProperty("initialFile", str(Path(positional[0])))

    # Development aid: render the window to a PNG and quit, so the layout can be
    # reviewed without a person having to hold the window open.
    if "--screenshot" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--screenshot") + 1])
        if "--preview-mode" in sys.argv:
            item = window.findChild(PreviewItem)
            if item is not None:
                item.setProperty("mode", sys.argv[sys.argv.index("--preview-mode") + 1])

        def capture() -> None:
            image = window.grabWindow()
            target.parent.mkdir(parents=True, exist_ok=True)
            saved = image.save(str(target))
            print(f"{'saved' if saved else 'FAILED to save'} {target} "
                  f"({image.width()}x{image.height()})", flush=True)
            app.quit()

        QTimer.singleShot(4000, capture)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
