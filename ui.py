# Binary Ninja UI bindings must be imported before PySide6.
from binaryninjaui import (
    Sidebar,
    SidebarContextSensitivity,
    SidebarWidget,
    SidebarWidgetLocation,
    SidebarWidgetType,
)
from binaryninja import execute_on_main_thread
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QLineEdit,
    QLabel,
)


class BoolHunterSidebarWidget(SidebarWidget):
    def __init__(self, name, frame, data):
        super().__init__(name)
        self.frame = frame
        self.bv = data
        self.results = []
        self._hunt_task = None
        self.setup_ui()
        self.bind_to_active_view()

    def _set_binary_view(self, bv):
        """Update the analysis target and discard results from a different view."""
        if bv is None or bv is self.bv:
            return
        try:
            if bv == self.bv:
                return
        except Exception:
            pass

        self.bv = bv
        self.results = []
        self.table.setRowCount(0)
        self.details.clear()

    def _binary_view_from_frame(self, frame):
        if frame is None:
            return None

        try:
            view = frame.getCurrentViewInterface()
            return view.getData() if view is not None else None
        except Exception:
            return None

    def bind_to_active_view(self):
        """Bind to the BinaryView active when the sidebar is shown or used."""
        sidebar = Sidebar.current()
        if sidebar is not None:
            active_bv = sidebar.currentData()
            if active_bv is not None:
                self._set_binary_view(active_bv)
                return self.bv

            self.frame = sidebar.currentFrame()

        self._set_binary_view(self._binary_view_from_frame(self.frame))
        return self.bv

    def notifyViewChanged(self, frame):
        self.frame = frame
        self._set_binary_view(self._binary_view_from_frame(frame))

    def showEvent(self, event):
        super().showEvent(event)
        self.bind_to_active_view()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)

        # Header / Search
        top_row = QHBoxLayout()
        self.hunt_btn = QPushButton("🎯 HUNT")
        self.hunt_btn.clicked.connect(self.on_hunt_clicked)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter results...")
        self.filter_edit.textChanged.connect(self.refresh_table)

        top_row.addWidget(self.hunt_btn)
        top_row.addWidget(self.filter_edit)
        self.layout.addLayout(top_row)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #a0a0a0; padding: 2px 0;")
        self.layout.addWidget(self.status_label)

        # Main Content
        self.splitter = QSplitter(Qt.Vertical)

        # Table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Function", "Score", "Address"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.doubleClicked.connect(self.on_double_click)

        self.splitter.addWidget(self.table)

        # Details
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setStyleSheet(
            "background-color: #2a2a2a; color: #e0e0e0; font-family: monospace;"
        )
        self.splitter.addWidget(self.details)

        self.layout.addWidget(self.splitter)

    def on_hunt_clicked(self):
        self.bind_to_active_view()
        if self.bv is None:
            return

        from .main import HunterTask

        self.results = []
        self.table.setRowCount(0)
        self.details.clear()
        self.hunt_btn.setEnabled(False)
        self.hunt_btn.setText("Hunting...")
        self.status_label.setText("Starting Boolean heuristic screening...")

        task = HunterTask(
            self.bv,
            lambda *args: self.on_hunt_progress(task, *args),
            lambda results: self.on_hunt_results(task, results),
            lambda results, cancelled: self.on_hunt_complete(task, results, cancelled),
        )
        self._hunt_task = task
        task.start()

    def on_hunt_progress(
        self,
        task,
        phase,
        scanned,
        total,
        priority_candidates,
        analyzed,
        results_found,
    ):
        execute_on_main_thread(
            lambda: self._update_hunt_progress(
                task,
                phase,
                scanned,
                total,
                priority_candidates,
                analyzed,
                results_found,
            )
        )

    def _update_hunt_progress(
        self,
        task,
        phase,
        scanned,
        total,
        priority_candidates,
        analyzed,
        results_found,
    ):
        if task is not self._hunt_task:
            return
        self.status_label.setText(
            f"{phase}: {scanned:,}/{total:,} analyzed · "
            f"{priority_candidates:,} priority candidates · "
            f"{results_found:,} results"
        )

    def on_hunt_results(self, task, results):
        execute_on_main_thread(lambda: self._append_hunt_results(task, results))

    def _append_hunt_results(self, task, results):
        if task is not self._hunt_task:
            return
        self.results.extend(results)
        query = self.filter_edit.text().lower()
        for res in sorted(results, key=lambda x: x.final_score, reverse=True):
            self._add_result_row(res, query)

    def on_hunt_complete(self, task, results, cancelled):
        execute_on_main_thread(
            lambda: self._finish_hunt(task, results, cancelled)
        )

    def _finish_hunt(self, task, results, cancelled):
        if task is not self._hunt_task:
            return
        self.results = results
        self.refresh_table()
        self.hunt_btn.setEnabled(True)
        self.hunt_btn.setText("🎯 HUNT AGAIN")
        state = "Cancelled" if cancelled else "Complete"
        self.status_label.setText(f"{state}: {len(results):,} Boolean candidates found")
        self._hunt_task = None

    def _add_result_row(self, res, query):
        if query and query not in res.func.name.lower():
            return

        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(res.func.name)
        name_item.setData(Qt.UserRole, res)

        score_item = QTableWidgetItem(f"{res.final_score}%")
        if res.final_score >= 90:
            score_item.setForeground(Qt.green)
        elif res.final_score >= 70:
            score_item.setForeground(Qt.cyan)

        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, score_item)
        self.table.setItem(row, 2, QTableWidgetItem(hex(res.func.start)))

    def refresh_table(self):
        query = self.filter_edit.text().lower()
        self.table.setRowCount(0)

        # Sort by score descending when a full refresh is requested, such as
        # search filtering or hunt completion. Live batches append efficiently.
        for res in sorted(self.results, key=lambda x: x.final_score, reverse=True):
            self._add_result_row(res, query)

    def on_selection_changed(self):
        items = self.table.selectedItems()
        if not items:
            return
        res = items[0].data(Qt.UserRole)

        text = "BOOLHUNTER ANALYSIS\n"
        text += f"Function:  {res.func.name}\n"
        text += f"Address:   {hex(res.func.start)}\n"
        text += f"Confidence: {res.final_score}%\n"
        text += f"Return:    {res.func.return_type}\n"
        text += "\nEVIDENCE:\n"
        for ev in res.evidence_list:
            text += f" ✓ {ev.message} (+{ev.score})\n"

        self.details.setText(text)

    def on_double_click(self, index):
        res = self.table.item(index.row(), 0).data(Qt.UserRole)
        self.bv.navigate(self.bv.view, res.func.start)


class BoolHunterSidebarWidgetType(SidebarWidgetType):
    def __init__(self):
        # Sidebar icons are 28x28 points; provide a HiDPI-ready 56x56 image.
        icon = QImage(56, 56, QImage.Format_RGB32)
        icon.fill(0)

        painter = QPainter()
        painter.begin(icon)
        painter.setFont(QFont("Open Sans", 44))
        painter.setPen(QColor(255, 255, 255, 255))
        painter.drawText(QRectF(0, 0, 56, 56), Qt.AlignCenter, "B")
        painter.end()

        super().__init__(icon, "BoolHunter")

    def createWidget(self, frame, data):
        return BoolHunterSidebarWidget("BoolHunter", frame, data)

    def defaultLocation(self):
        return SidebarWidgetLocation.RightContent

    def contextSensitivity(self):
        # Keep one widget alive and update its target from notifyViewChanged and
        # the active sidebar context. This avoids Binary Ninja's no-file fallback
        # when the sidebar is created before a per-tab context is available.
        return SidebarContextSensitivity.SelfManagedSidebarContext


# Register the UI at load time using the supported sidebar API.
Sidebar.addSidebarWidgetType(BoolHunterSidebarWidgetType())
