from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, 
    QTableWidgetItem, QHeaderView, QWidget, QLabel, 
    QAbstractItemView, QSplitter, QTextEdit, QLineEdit
)
from PySide6.QtCore import Qt
from binaryninjaui import DockContextHandler, DockHandler
from binaryninja import BinaryView, execute_on_main_thread

class BoolHunterDockWidget(QWidget, DockContextHandler):
    def __init__(self, parent, name, bv):
        QWidget.__init__(self, parent)
        DockContextHandler.__init__(self, self, name)
        self.bv = bv
        self.results = []
        self.setup_ui()

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
        self.details.setStyleSheet("background-color: #2a2a2a; color: #e0e0e0; font-family: monospace;")
        self.splitter.addWidget(self.details)

        self.layout.addWidget(self.splitter)

    def on_hunt_clicked(self):
        from .main import HunterTask
        self.hunt_btn.setEnabled(False)
        self.hunt_btn.setText("Hunting...")
        task = HunterTask(self.bv, self.on_hunt_complete)
        task.start()

    def on_hunt_complete(self, results):
        self.results = results
        execute_on_main_thread(self.refresh_table)
        execute_on_main_thread(lambda: self.hunt_btn.setEnabled(True))
        execute_on_main_thread(lambda: self.hunt_btn.setText("🎯 HUNT AGAIN"))

    def refresh_table(self):
        query = self.filter_edit.text().lower()
        self.table.setRowCount(0)
        
        # Sort by score descending
        sorted_res = sorted(self.results, key=lambda x: x.final_score, reverse=True)
        
        for res in sorted_res:
            if query and query not in res.func.name.lower():
                continue
            
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            name_item = QTableWidgetItem(res.func.name)
            name_item.setData(Qt.UserRole, res)
            
            score_item = QTableWidgetItem(f"{res.final_score}%")
            if res.final_score >= 90: score_item.setForeground(Qt.green)
            elif res.final_score >= 70: score_item.setForeground(Qt.cyan)

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, score_item)
            self.table.setItem(row, 2, QTableWidgetItem(hex(res.func.start)))

    def on_selection_changed(self):
        items = self.table.selectedItems()
        if not items: return
        res = items[0].data(Qt.UserRole)
        
        text = f"BOOLHUNTER ANALYSIS\n"
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