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
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from .ai import AIAnalystError, AIProviderConfig
from .engine import BoolHunterEngine


class AIConfigDialog(QDialog):
    """Small session-only configuration dialog for an OpenAI-compatible API."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BoolHunter AI Analyst Settings")
        self.setModal(True)

        form = QFormLayout(self)
        self.provider_edit = QLineEdit(config.provider_name if config else "OpenAI-compatible")
        self.base_url_edit = QLineEdit(config.base_url if config else "")
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
        self.api_key_edit = QLineEdit(config.api_key if config else "")
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit(config.model if config else "")
        self.model_edit.setPlaceholderText("Model name")
        self.timeout_edit = QLineEdit(str(config.timeout_seconds if config else 30))
        self.ca_bundle_edit = QLineEdit(config.ca_bundle_path if config else "")
        self.ca_bundle_edit.setPlaceholderText("/path/to/trusted-ca-bundle.pem (optional)")

        form.addRow("Provider (optional):", self.provider_edit)
        form.addRow("Base URL:", self.base_url_edit)
        form.addRow("API key:", self.api_key_edit)
        form.addRow("Model:", self.model_edit)
        form.addRow("Timeout (seconds):", self.timeout_edit)
        form.addRow("Trusted CA bundle (optional):", self.ca_bundle_edit)

        note = QLabel(
            "Configuration is kept only for this BoolHunter session. A custom CA "
            "bundle must be a PEM file; TLS certificate and hostname verification "
            "remain enabled."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #a0a0a0;")
        form.addRow(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def config(self) -> AIProviderConfig:
        try:
            timeout_seconds = float(self.timeout_edit.text().strip())
        except ValueError:
            raise AIAnalystError("AI Analyst timeout must be a number.")

        config = AIProviderConfig(
            base_url=self.base_url_edit.text(),
            api_key=self.api_key_edit.text(),
            model=self.model_edit.text(),
            provider_name=self.provider_edit.text().strip() or "OpenAI-compatible",
            timeout_seconds=timeout_seconds,
            ca_bundle_path=self.ca_bundle_edit.text().strip(),
        )
        config.validate()
        return config


class BoolHunterSidebarWidget(SidebarWidget):
    def __init__(self, name, frame, data):
        super().__init__(name)
        self.frame = frame
        self.bv = data
        self._engine = BoolHunterEngine(data) if data is not None else None
        self.results = []
        self._hunt_results = []
        self._topic_results = []
        self._hunt_task = None
        self._ai_task = None
        self._chat_task = None
        self._ai_config = None
        self._ai_interpretations = {}
        self._ai_history = []
        self._chat_lines = []
        self.setup_ui()
        self.bind_to_active_view()

    def _set_binary_view(self, bv):
        """Update the analysis target and discard results from a different view."""
        if bv is self.bv:
            return
        try:
            if bv is not None and bv == self.bv:
                return
        except Exception:
            pass

        self.bv = bv
        if self._hunt_task is not None:
            self._hunt_task.cancel()
            self._hunt_task = None
            self.hunt_btn.setEnabled(True)
            self.hunt_btn.setText("🎯 HUNT")
        if self._ai_task is not None:
            self._ai_task.cancel()
            self._ai_task = None
            self.ai_analyze_btn.setEnabled(False)
        if self._chat_task is not None:
            self._chat_task.cancel()
            self._chat_task = None
        self._engine = BoolHunterEngine(bv) if bv is not None else None
        self.results = []
        self._hunt_results = []
        self._topic_results = []
        self._ai_interpretations = {}
        self._ai_history = []
        self._chat_lines = []
        self.chat_transcript.clear()
        self.chat_send_btn.setEnabled(True)
        self.chat_clear_btn.setEnabled(True)
        self.chat_cancel_btn.setEnabled(False)
        self.chat_input.setEnabled(bv is not None)
        self.chat_send_btn.setEnabled(bv is not None)
        self.hunt_btn.setEnabled(bv is not None)
        self.table.setRowCount(0)
        self.details.clear()
        self.ai_analyze_btn.setEnabled(False)

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

        # Existing Hunt / search controls
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
        self.status_label.setAccessibleName("BoolHunter status")
        self.status_label.setStyleSheet("color: #a0a0a0; padding: 2px 0;")
        self.layout.addWidget(self.status_label)

        # Optional AI controls are separate from deterministic Hunt controls.
        ai_row = QHBoxLayout()
        self.ai_config_btn = QPushButton("Configure AI...")
        self.ai_config_btn.clicked.connect(self.on_configure_ai)
        self.ai_analyze_btn = QPushButton("Analyze with AI")
        self.ai_analyze_btn.setEnabled(False)
        self.ai_analyze_btn.clicked.connect(self.on_analyze_with_ai)
        ai_row.addWidget(self.ai_config_btn)
        ai_row.addWidget(self.ai_analyze_btn)
        self.layout.addLayout(ai_row)

        self.chat_transcript = QTextEdit()
        self.chat_transcript.setReadOnly(True)
        self.chat_transcript.setMaximumHeight(180)
        self.chat_transcript.setAccessibleName("Chat conversation")
        self.chat_transcript.setPlaceholderText(
            "Ask BoolHunter to investigate a topic across the whole binary."
        )
        conversation_label = QLabel("Conversation:")
        conversation_label.setBuddy(self.chat_transcript)
        self.layout.addWidget(conversation_label)
        self.layout.addWidget(self.chat_transcript)

        chat_row = QHBoxLayout()
        message_label = QLabel("Message:")
        self.chat_input = QLineEdit()
        self.chat_input.setAccessibleName("Chat message")
        self.chat_input.setPlaceholderText(
            "Double down on purchase-related booleans..."
        )
        self.chat_input.setEnabled(self.bv is not None)
        message_label.setBuddy(self.chat_input)
        self.chat_input.returnPressed.connect(self.on_chat_send)
        self.chat_send_btn = QPushButton("Send")
        self.chat_send_btn.setEnabled(self.bv is not None)
        self.chat_send_btn.clicked.connect(self.on_chat_send)
        self.chat_cancel_btn = QPushButton("Cancel")
        self.chat_cancel_btn.setEnabled(False)
        self.chat_cancel_btn.setToolTip(
            "Stops scans immediately. An in-flight provider request finishes or times out first."
        )
        self.chat_cancel_btn.clicked.connect(self.on_chat_cancel)
        self.chat_clear_btn = QPushButton("Clear chat")
        self.chat_clear_btn.clicked.connect(self.clear_chat)
        chat_row.addWidget(message_label)
        chat_row.addWidget(self.chat_input)
        chat_row.addWidget(self.chat_send_btn)
        chat_row.addWidget(self.chat_cancel_btn)
        chat_row.addWidget(self.chat_clear_btn)
        self.layout.addLayout(chat_row)

        # Main Content
        self.splitter = QSplitter(Qt.Vertical)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Function", "Category", "Score", "Address"])

        # Keep the result columns wide enough to inspect, while allowing the
        # sidebar to expose them through its horizontal scrollbar when the
        # available width is smaller than the content.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setMinimumSectionSize(96)
        header.setDefaultSectionSize(180)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.resizeSection(0, 320)
        header.resizeSection(1, 220)
        header.resizeSection(2, 120)
        header.resizeSection(3, 180)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.itemClicked.connect(self.on_item_clicked)
        self.table.doubleClicked.connect(self.on_double_click)
        self.splitter.addWidget(self.table)

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
        if self._chat_task is not None:
            self.status_label.setText("AI chat is active; wait for it to finish before HUNT.")
            return

        from .main import HunterTask

        self.results = []
        self._hunt_results = []
        self._topic_results = []
        self._ai_interpretations = {}
        self.table.setRowCount(0)
        self.details.clear()
        self.ai_analyze_btn.setEnabled(False)
        self.hunt_btn.setEnabled(False)
        self.chat_input.setEnabled(False)
        self.chat_send_btn.setEnabled(False)
        self.hunt_btn.setText("Hunting...")
        self.status_label.setText("Starting Boolean heuristic screening...")

        task = HunterTask(
            self.bv,
            lambda *args: self.on_hunt_progress(task, *args),
            lambda results: self.on_hunt_results(task, results),
            lambda results, cancelled: self.on_hunt_complete(task, results, cancelled),
            self._engine,
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
        self._hunt_results.extend(results)
        if self._topic_results:
            self._merge_results()
            self.refresh_table()
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
        self._hunt_results = list(results)
        self._merge_results()
        self.refresh_table()
        self.hunt_btn.setEnabled(True)
        self.hunt_btn.setText("🎯 HUNT AGAIN")
        self.chat_input.setEnabled(self.bv is not None)
        self.chat_send_btn.setEnabled(self.bv is not None)
        state = "Cancelled" if cancelled else "Complete"
        self.status_label.setText(f"{state}: {len(results):,} Boolean candidates found")
        self._hunt_task = None

    def on_configure_ai(self):
        dialog = AIConfigDialog(self._ai_config, self)
        if not dialog.exec():
            return
        try:
            self._ai_config = dialog.config()
        except AIAnalystError as error:
            self.status_label.setText(f"AI Analyst: {error}")
            return
        self.status_label.setText(
            f"AI Analyst configured: {self._ai_config.provider_name} / {self._ai_config.model}"
        )

    def _selected_result(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item is not None else None

    def on_analyze_with_ai(self):
        result = self._selected_result()
        if result is None:
            self.status_label.setText("AI Analyst: select a BoolHunter result first.")
            return
        if self._ai_config is None:
            self.status_label.setText("AI Analyst: configure an endpoint before analysis.")
            return
        try:
            self._ai_config.validate()
        except AIAnalystError as error:
            self.status_label.setText(f"AI Analyst: {error}")
            return

        from .main import AIAnalysisTask

        self.ai_analyze_btn.setEnabled(False)
        self.status_label.setText("AI Analyst: preparing selected function context...")
        task = AIAnalysisTask(
            result,
            self._ai_config,
            lambda analysis, error, cancelled: self.on_ai_complete(
                task,
                result,
                analysis,
                error,
                cancelled,
            ),
        )
        self._ai_task = task
        task.start()

    def on_ai_complete(self, task, result, analysis, error, cancelled):
        execute_on_main_thread(
            lambda: self._finish_ai_analysis(task, result, analysis, error, cancelled)
        )

    def _finish_ai_analysis(self, task, result, analysis, error, cancelled):
        if task is not self._ai_task:
            return
        self._ai_task = None
        self.ai_analyze_btn.setEnabled(self._selected_result() is not None)

        if cancelled:
            self.status_label.setText("AI Analyst: cancelled.")
            return
        if error:
            self.status_label.setText(f"AI Analyst: {error}")
            return

        self._ai_interpretations[result.func.start] = analysis
        self.status_label.setText("AI Analyst: interpretation complete.")
        selected = self._selected_result()
        if selected is result:
            self._show_selected_analysis(result)

    def _append_chat_line(self, speaker, text):
        self._chat_lines.append(f"{speaker}: {text}")
        self._chat_lines = self._chat_lines[-80:]
        self.chat_transcript.setPlainText("\n\n".join(self._chat_lines))
        scrollbar = self.chat_transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _merge_results(self):
        merged = {item.func.start: item for item in self._hunt_results}
        merged.update({item.func.start: item for item in self._topic_results})
        self.results = list(merged.values())

    def on_chat_send(self):
        self.bind_to_active_view()
        query = self.chat_input.text().strip()
        if not query:
            self.status_label.setText("AI chat: enter a request first.")
            return
        if self.bv is None or self._engine is None:
            self.status_label.setText("AI chat: no active BinaryView.")
            return
        if self._chat_task is not None:
            return
        if self._hunt_task is not None:
            self.status_label.setText("HUNT is active; wait for it to finish before AI chat.")
            return
        if self._ai_config is None:
            self.status_label.setText("AI chat: configure an endpoint first.")
            return
        try:
            self._ai_config.validate()
        except AIAnalystError as error:
            self.status_label.setText(f"AI chat: {error}")
            return

        from .main import AIChatTask

        self._topic_results = []
        self._merge_results()
        self.refresh_table()
        self.chat_input.clear()
        self._append_chat_line("You", query)
        self.hunt_btn.setEnabled(False)
        self.chat_send_btn.setEnabled(False)
        self.chat_clear_btn.setEnabled(False)
        self.chat_cancel_btn.setEnabled(True)
        self.status_label.setText("AI chat: interpreting request...")
        history = list(self._ai_history)
        task = AIChatTask(
            self._engine,
            query,
            history,
            self._ai_config,
            lambda *args: self.on_chat_progress(task, *args),
            lambda result, error, cancelled: self.on_chat_complete(
                task, query, result, error, cancelled
            ),
        )
        self._chat_task = task
        task.start()

    def on_chat_progress(self, task, phase, considered, total, deeply_analyzed):
        execute_on_main_thread(lambda: self._update_chat_progress(
            task, phase, considered, total, deeply_analyzed
        ))

    def _update_chat_progress(self, task, phase, considered, total, deeply_analyzed):
        if task is not self._chat_task:
            return
        if total:
            self.status_label.setText(
                f"AI chat: {phase} {considered:,}/{total:,}; "
                f"{deeply_analyzed:,} deeply analyzed."
            )
        else:
            self.status_label.setText(f"AI chat: {phase.lower()}...")

    def on_chat_cancel(self):
        if self._chat_task is not None:
            self._chat_task.cancel()
            self.chat_cancel_btn.setEnabled(False)
            self.status_label.setText(
                "AI chat: cancellation requested; waiting for the provider request or scan to stop."
            )

    def on_chat_complete(self, task, query, result, error, cancelled):
        execute_on_main_thread(lambda: self._finish_chat(
            task, query, result, error, cancelled
        ))

    def _finish_chat(self, task, query, result, error, cancelled):
        if task is not self._chat_task:
            return
        self._chat_task = None
        self.chat_send_btn.setEnabled(True)
        self.chat_clear_btn.setEnabled(True)
        self.chat_cancel_btn.setEnabled(False)
        self.hunt_btn.setEnabled(self.bv is not None)
        if error:
            self._append_chat_line("BoolHunter", f"Request failed: {error}")
            self.status_label.setText(f"AI chat: {error}")
            return
        if result is None:
            self.status_label.setText("AI chat: cancelled before analysis completed.")
            return

        self._append_chat_line("BoolHunter", result.plan.reply)
        self._ai_history.extend([
            {"role": "user", "content": query},
            {"role": "assistant", "content": result.plan.reply},
        ])
        self._ai_history = self._ai_history[-12:]
        if result.scan is None:
            self.status_label.setText("AI chat: clarification requested.")
            return

        scan = result.scan
        self._topic_results = list(scan.results)
        self._merge_results()
        self.refresh_table()
        state = "cancelled" if cancelled or scan.cancelled else (
            "complete" if scan.complete else "partial"
        )
        summary = (
            f"Targeted scan {state}: considered {scan.functions_considered:,}; "
            f"deeply analyzed {scan.functions_deeply_analyzed:,}; "
            f"returned {len(scan.results):,} candidate(s); "
            f"limited {scan.functions_limited:,}; "
            f"string-reference index limited: {scan.string_index_limited}; "
            f"elapsed {scan.elapsed_seconds:.1f}s."
        )
        self._append_chat_line("BoolHunter", summary)
        self.status_label.setText(summary)

        if scan.results:
            target = scan.results[0].func.start
            for row in range(self.table.rowCount()):
                address_item = self.table.item(row, 3)
                if address_item is not None and address_item.text().lower() == hex(target).lower():
                    self.table.selectRow(row)
                    self.table.scrollToItem(
                        self.table.item(row, 0), QAbstractItemView.PositionAtCenter
                    )
                    break

    def clear_chat(self):
        if self._chat_task is not None:
            return
        self._ai_history.clear()
        self._chat_lines.clear()
        self.chat_transcript.clear()
        self.status_label.setText("AI chat cleared.")

    def _add_result_row(self, res, query):
        category = getattr(res, "category", "Other")
        searchable_text = f"{res.func.name} {category}".lower()
        if query and query not in searchable_text:
            return

        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(res.func.name)
        name_item.setData(Qt.UserRole, res)

        category_item = QTableWidgetItem(category)

        score_item = QTableWidgetItem(f"{res.final_score}%")
        if res.final_score >= 90:
            score_item.setForeground(Qt.green)
        elif res.final_score >= 70:
            score_item.setForeground(Qt.cyan)

        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, category_item)
        self.table.setItem(row, 2, score_item)
        self.table.setItem(row, 3, QTableWidgetItem(hex(res.func.start)))

    def refresh_table(self):
        query = self.filter_edit.text().lower()
        self.table.setRowCount(0)

        # Sort by score descending when a full refresh is requested, such as
        # search filtering or hunt completion. Live batches append efficiently.
        for res in sorted(self.results, key=lambda x: x.final_score, reverse=True):
            self._add_result_row(res, query)

    def on_selection_changed(self):
        result = self._selected_result()
        self.ai_analyze_btn.setEnabled(result is not None and self._ai_task is None)
        if result is not None:
            self._show_selected_analysis(result)

    def _show_selected_analysis(self, res):
        text = "BOOLHUNTER DETERMINISTIC ANALYSIS\n"
        text += f"Function:  {res.func.name}\n"
        text += f"Address:   {hex(res.func.start)}\n"
        text += f"Score:      {res.final_score}%\n"
        text += f"Category:  {getattr(res, 'category', 'Other')}\n"
        text += f"Return:    {res.func.return_type}\n"
        text += "\nDETERMINISTIC EVIDENCE:\n"
        for ev in res.evidence_list:
            text += f" ✓ {ev.message} (+{ev.score})\n"

        if res.topic_evidence:
            text += "\nTARGETED TOPIC MATCHES (do not affect score):\n"
            for evidence in res.topic_evidence:
                text += f" • {evidence}\n"

        interpretation = self._ai_interpretations.get(res.func.start)
        if interpretation:
            text += "\nAI ANALYST INTERPRETATION (does not alter BoolHunter score):\n"
            text += interpretation
        else:
            text += "\nAI ANALYST: No interpretation requested for this result.\n"
        self.details.setText(text)

    def _navigate_to_result(self, result):
        if result is None or self.bv is None:
            return
        self.bv.navigate(self.bv.view, result.func.start)

    def on_item_clicked(self, item):
        """Navigate immediately when any cell in a result row is clicked."""
        self._navigate_to_result(self._selected_result())

    def on_double_click(self, index):
        # Keep double-click navigation as a backward-compatible fallback.
        self._navigate_to_result(self._selected_result())


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
