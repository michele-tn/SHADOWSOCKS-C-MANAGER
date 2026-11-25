"""Qt desktop console backed by the real local Bash administration engine."""
from __future__ import annotations

import os
import platform
import secrets
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QStandardPaths, Qt
from PySide6.QtGui import QCloseEvent, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpinBox, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)

from scmanager.models import CIPHERS, ConfigurationError, ServerConfig, load_config
from scmanager.environment import x11_forwarded

STYLE = """
QWidget { background: #101722; color: #e8eef6; font-family: 'Segoe UI'; font-size: 14px; }
QLabel { background: transparent; }
QMainWindow { background: #101722; }
QFrame#sidebar { background: #0b111b; border-right: 1px solid #263244; }
QFrame#card { background: #172231; border: 1px solid #2b3a4f; border-radius: 14px; }
QFrame#card QLabel { background: transparent; }
QLabel#eyebrow { color: #6cddd0; font-size: 11px; font-weight: 700; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#brand { font-size: 24px; font-weight: 700; }
QLabel#subtitle { color: #a8b8cc; }
QLabel#badge { background: #203346; color: #91e8dd; border-radius: 8px; padding: 8px 12px; }
QPushButton { background: #243349; border: 1px solid #3b506a; border-radius: 8px; padding: 11px 16px; text-align: left; }
QPushButton:hover { background: #30465f; border-color: #71d8cf; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #81e8db; }
QPushButton:checked { background: #153b43; color: #91f0df; border-color: #397f7e; }
QPushButton#primary { background: #70e0cd; color: #082c32; font-weight: 700; border: none; }
QPushButton#primary:hover { background: #a4f6e7; }
QPushButton:disabled { color: #8190a3; background: #202b3b; border-color: #303d4e; }
QPushButton#primary:disabled { background: #263547; color: #8495aa; }
QLineEdit, QComboBox, QSpinBox { background: #0f1825; border: 1px solid #3b506a; border-radius: 7px; padding: 9px; min-height: 22px; }
QPlainTextEdit { background: #0b121c; border: 1px solid #2b3a4f; border-radius: 10px; color: #bdcedf; padding: 12px; font-family: 'Consolas'; font-size: 12px; }
QProgressBar { background: #243349; border: none; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #70e0cd; }
QSplitter::handle { background: #263244; height: 2px; }
QToolTip { background: #263a50; color: #ffffff; border: 1px solid #70e0cd; }
"""


def label(text: str, role: str = "") -> QLabel:
    """Build a wrapping plain-text label with an optional design role."""
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def button(text: str, primary: bool = False) -> QPushButton:
    """Build a keyboard-focusable action."""
    widget = QPushButton(text.replace("&", "&&"))
    if primary:
        widget.setObjectName("primary")
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class ManagerWindow(QMainWindow):
    """One GUI owner for process state, forms and output buffers."""

    def __init__(self, project: Path) -> None:
        """Create the workspace; no administrative process starts automatically."""
        super().__init__()
        if platform.system() == "Windows":
            # The offscreen Qt platform does not populate the Windows font database.
            for directory in QStandardPaths.standardLocations(QStandardPaths.StandardLocation.FontsLocation):
                for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
                    font_path = Path(directory) / name
                    if font_path.is_file():
                        QFontDatabase.addApplicationFont(str(font_path))
        self.project = project
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.receive_output)
        self.process.finished.connect(self.operation_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.pending = ""
        self.buffer = ""
        self.running = False
        self.cancel_requested = False
        self.admin_available = platform.system() == "Linux" and os.geteuid() == 0
        self.setWindowTitle("Shadowsocks-C Manager | Operations Console")
        self.resize(1240, 940)
        self.setMinimumSize(960, 760)
        style = STYLE if platform.system() == "Windows" else STYLE.replace("Segoe UI", "DejaVu Sans").replace("Consolas", "DejaVu Sans Mono")
        self.setStyleSheet(style)
        self.build_workspace()
        self.select_mode(0)

    def build_workspace(self) -> None:
        """Compose navigation, contextual forms and the live operation console."""
        root = QWidget()
        horizontal = QHBoxLayout(root)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(256)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(24, 30, 24, 24)
        navigation.setSpacing(14)
        navigation.addWidget(label("SC / OPERATIONS", "eyebrow"))
        brand = label("Shadowsocks\nC Manager")
        brand.setObjectName("brand")
        brand.setFont(QFont("Segoe UI", 23, QFont.Weight.Bold))
        navigation.addWidget(brand)
        navigation.addSpacing(32)
        navigation.addWidget(label("WORKFLOWS", "eyebrow"))
        self.navigation: list[QPushButton] = []
        for index, text in enumerate(("01   Fresh installation", "02   Legacy migration", "03   Backup & rollback")):
            action = button(text)
            action.setCheckable(True)
            action.clicked.connect(lambda checked=False, number=index: self.select_mode(number))
            self.navigation.append(action)
            navigation.addWidget(action)
        navigation.addStretch()
        navigation.addWidget(label("AUDITED SOURCE", "eyebrow"))
        navigation.addWidget(label("50f1ae54f737\nDevelopment snapshot", "subtitle"))
        navigation.addSpacing(20)
        navigation.addWidget(label("Engine on Ubuntu\nDisplay via SSH / X11" if x11_forwarded()
                                   else "Local execution only\nUbuntu 22.04.5 LTS target", "subtitle"))
        horizontal.addWidget(sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("INFRASTRUCTURE / SECURE PROXY", "eyebrow"))
        self.title = label("", "title")
        titles.addWidget(self.title)
        heading.addLayout(titles, 1)
        ready_status = "Ready · SSH/X11 display" if x11_forwarded() else "Ready · Ubuntu engine"
        self.badge = label(ready_status if self.admin_available else "Inspection only · " + platform.system(), "badge")
        heading.addWidget(self.badge)
        layout.addLayout(heading)
        self.description = label("", "subtitle")
        layout.addWidget(self.description)
        split = QSplitter(Qt.Orientation.Vertical)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.install_page())
        self.pages.addWidget(self.migration_page())
        self.pages.addWidget(self.backup_page())
        split.addWidget(self.pages)
        console_panel = QWidget()
        console_layout = QVBoxLayout(console_panel)
        console_layout.setContentsMargins(0, 12, 0, 0)
        console_heading = QHBoxLayout()
        console_heading.addWidget(label("OPERATION ACTIVITY", "eyebrow"), 1)
        self.cancel = button("Cancel operation")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_operation)
        console_heading.addWidget(self.cancel)
        console_layout.addLayout(console_heading)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        console_layout.addWidget(self.progress)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(3000)
        self.console.setAccessibleName("Operation activity and errors")
        console_layout.addWidget(self.console)
        split.addWidget(console_panel)
        split.setSizes([480, 260])
        layout.addWidget(split, 1)
        self.status = label("No operation has run. Remote connectivity has not been tested.", "subtitle")
        layout.addWidget(self.status)
        horizontal.addWidget(content, 1)
        self.setCentralWidget(root)
        if not self.admin_available:
            self.console.appendPlainText("[INFO] Inspection mode. For administration, run bash launch_gui.sh on Ubuntu in your MobaXterm SSH/X11 session.")

    def card(self) -> tuple[QFrame, QVBoxLayout]:
        """Create a reusable content surface."""
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        box = QVBoxLayout(frame)
        box.setContentsMargins(24, 20, 24, 20)
        box.setSpacing(12)
        return frame, box

    def install_page(self) -> QWidget:
        """Build the fresh configuration wizard without exposing credentials."""
        frame, box = self.card()
        box.addWidget(label("SERVER CONFIGURATION", "eyebrow"))
        form = QFormLayout()
        form.setSpacing(10)
        self.address = QLineEdit("0.0.0.0")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(8388)
        self.cipher = QComboBox()
        self.cipher.addItems(CIPHERS)
        self.cipher.setCurrentText("aes-256-gcm")
        self.protocol = QComboBox()
        self.protocol.addItems(("tcp_and_udp", "tcp_only", "udp_only"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Enter a password or generate a secure one")
        self.password.setAccessibleName("Server password, masked")
        password_row = QHBoxLayout()
        password_row.addWidget(self.password, 1)
        generate = button("Generate")
        generate.clicked.connect(self.generate_password)
        password_row.addWidget(generate)
        form.addRow("Listening &address", self.address)
        form.addRow("Listening &port", self.port)
        form.addRow("Encryption &method", self.cipher)
        form.addRow("Protocol &mode", self.protocol)
        password_label = QLabel("&Password")
        password_label.setBuddy(self.password)
        form.addRow(password_label, password_row)
        box.addLayout(form)
        box.addWidget(label("The engine checks port ownership, builds the pinned snapshot and creates a recovery backup before installation. Firewall rules remain under your control.", "subtitle"))
        actions = QHBoxLayout()
        validate = button("Validate configuration")
        validate.clicked.connect(self.validate_form)
        actions.addWidget(validate)
        self.install_action = button("Prepare installation", True)
        self.install_action.setEnabled(self.admin_available)
        self.install_action.clicked.connect(self.start_installation)
        actions.addWidget(self.install_action)
        box.addLayout(actions)
        box.addStretch()
        return frame

    def migration_page(self) -> QWidget:
        """Inspect a local legacy file; the engine independently discovers the live source."""
        frame, box = self.card()
        box.addWidget(label("PRESERVE THE WORKING CONFIGURATION", "eyebrow"))
        box.addWidget(label("Inspect first. Cut over only when ready."))
        box.addWidget(label("Credentials, cipher, endpoint and protocol must remain compatible. The original file is never rewritten. Unknown options stop the workflow.", "subtitle"))
        path_row = QHBoxLayout()
        self.source_path = QLineEdit()
        self.source_path.setPlaceholderText("Select a legacy JSON configuration for inspection")
        self.source_path.setAccessibleName("Legacy configuration path")
        path_row.addWidget(self.source_path, 1)
        browse = button("Browse…")
        browse.clicked.connect(self.browse_source)
        path_row.addWidget(browse)
        box.addLayout(path_row)
        self.inspection = label("No configuration inspected.", "subtitle")
        box.addWidget(self.inspection)
        inspect = button("Inspect compatibility")
        inspect.clicked.connect(self.inspect_source)
        box.addWidget(inspect)
        box.addStretch()
        box.addWidget(label("LIVE MIGRATION", "eyebrow"))
        box.addWidget(label("The Ubuntu engine discovers the actual service and source independently. Inspection above does not select or authorize a server configuration.", "subtitle"))
        self.migrate_action = button("Discover & prepare migration", True)
        self.migrate_action.setEnabled(self.admin_available)
        self.migrate_action.clicked.connect(lambda: self.start_engine(["migrate"]))
        box.addWidget(self.migrate_action)
        return frame

    def backup_page(self) -> QWidget:
        """Expose backup creation, inventory and a deliberate restore workflow."""
        frame, box = self.card()
        box.addWidget(label("RECOVERY WORKSPACE", "eyebrow"))
        box.addWidget(label("Verified snapshots. Deliberate recovery."))
        box.addWidget(label("Snapshots live in /var/backups/shadowsocks-c. Checksums are verified before restoration. A safety snapshot captures the current state before rollback.", "subtitle"))
        self.backup_action = button("Create verified backup", True)
        self.backup_action.clicked.connect(lambda: self.start_engine(["backup"]))
        self.list_action = button("List backups & integrity")
        self.list_action.clicked.connect(lambda: self.start_engine(["list"]))
        box.addWidget(self.backup_action)
        box.addWidget(self.list_action)
        box.addSpacing(16)
        self.backup_path = QLineEdit()
        self.backup_path.setPlaceholderText("Full snapshot directory from the inventory")
        self.backup_path.setAccessibleName("Snapshot directory to restore")
        box.addWidget(self.backup_path)
        self.restore_action = button("Review rollback impact")
        self.restore_action.clicked.connect(self.start_restore)
        box.addWidget(self.restore_action)
        for action in (self.backup_action, self.list_action, self.restore_action):
            action.setEnabled(self.admin_available)
        box.addStretch()
        box.addWidget(label("No automatic retention deletion. Legacy packages remain installed. A failed recovery keeps the snapshot and its diagnostics for manual intervention.", "subtitle"))
        return frame

    def select_mode(self, index: int) -> None:
        """Keep navigation, title and contextual page synchronized."""
        titles = ("Fresh installation", "Legacy migration", "Backup & rollback")
        descriptions = (
            "Configure a new server with a clear path from validation to verified startup.",
            "Preserve what works. Review compatibility before a controlled service cutover.",
            "Protect the current state and restore an earlier installation with verified evidence.",
        )
        self.pages.setCurrentIndex(index)
        self.title.setText(titles[index])
        self.description.setText(descriptions[index])
        for number, action in enumerate(self.navigation):
            action.setChecked(number == index)

    def configuration(self) -> ServerConfig:
        """Validate the current form through the same backend schema."""
        return ServerConfig.model_validate({"server": self.address.text(), "server_port": self.port.value(),
            "password": self.password.text(), "method": self.cipher.currentText(),
            "mode": self.protocol.currentText()})

    def validate_form(self) -> bool:
        """Report a redacted validation result without showing model inputs."""
        from pydantic import ValidationError
        try:
            self.configuration()
        except ValidationError:
            self.status.setText("Check the literal IP address, password, method and protocol. Ports must be 1024–65535.")
            return False
        self.status.setText("Configuration profile verified. Service startup and client relay have not been tested.")
        return True

    def generate_password(self) -> None:
        """Generate a masked random password without logging it."""
        self.password.setText(secrets.token_urlsafe(32))
        self.status.setText("Secure random password generated and masked. It will be stored privately on the target.")

    def browse_source(self) -> None:
        """Choose a local JSON file without administrative effects."""
        path, _ = QFileDialog.getOpenFileName(self, "Inspect legacy configuration", "", "JSON (*.json);;All files (*)")
        if path:
            self.source_path.setText(path)
            self.inspect_source()

    def inspect_source(self) -> None:
        """Show only nonsensitive compatibility facts."""
        try:
            config = load_config(Path(self.source_path.text()).absolute())
            self.inspection.setText(f"PROFILE VERIFIED · {config.server}:{config.server_port}\n{config.method} · {config.mode}\nPassword present and hidden. Source file unchanged. Live runtime overrides are not inspected here.")
        except (ConfigurationError, OSError, ValueError):
            self.inspection.setText("BLOCKED · Invalid JSON, unsupported options or unsafe path. Source unchanged. See the supported profile in the migration guide.")

    def start_installation(self) -> None:
        """Start the engine, then supply configuration through the input pipe."""
        if self.validate_form():
            self.start_engine(["install", "--stdin"])

    def start_restore(self) -> None:
        """Require an explicit snapshot path before starting review."""
        path = self.backup_path.text().strip()
        if not path.startswith("/var/backups/shadowsocks-c/"):
            self.status.setText("Select a full snapshot path from /var/backups/shadowsocks-c.")
            return
        self.start_engine(["rollback", path])

    def start_engine(self, arguments: list[str]) -> None:
        """Launch a single local process group; no shell command concatenation."""
        if self.running or not self.admin_available:
            return
        self.running = True
        self.cancel_requested = False
        self.pending = ""
        self.buffer = ""
        self.pages.setEnabled(False)
        self.cancel.setEnabled(True)
        self.progress.setRange(0, 0)
        self.badge.setText("Running · local engine")
        self.status.setText("Preparing operation. Typed confirmation is required before cutover.")
        self.console.appendPlainText("\n[INFO] Starting " + arguments[0])
        self.process.setWorkingDirectory(str(self.project))
        self.process.start("/usr/bin/setsid", ["/bin/bash", str(self.project / "shadowsocks-c-manager.sh"), *arguments])

    def receive_output(self) -> None:
        """Buffer complete lines so prompt markers survive arbitrary pipe chunks."""
        self.buffer += bytes(self.process.readAllStandardOutput().data()).decode("utf-8", errors="replace")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line == "SCM_INPUT:CONFIG":
                self.process.write(self.configuration().target_bytes().replace(b"\n", b"") + b"\n")
                self.password.clear()
            elif line.startswith("SCM_PROMPT:"):
                self.confirm_engine(line.partition(":")[2])
            else:
                self.console.appendPlainText(line)

    def confirm_engine(self, word: str) -> None:
        """Display the real impact and require exact typed consent."""
        if self.cancel_requested:
            self.process.write(b"CANCEL\n")
            return
        self.badge.setText("Awaiting confirmation")
        impact = self.console.toPlainText()[-5000:]
        answer, accepted = QInputDialog.getText(self, "Review operation: " + word,
            impact + f"\n\nType {word} to continue. Cancel stops this operation.")
        self.process.write(((answer if accepted and answer == word else "CANCEL") + "\n").encode())
        self.badge.setText("Running · local engine")

    def cancel_operation(self) -> None:
        """Request TERM for the whole group; wait for recovery before unlocking UI."""
        if self.running and not self.cancel_requested:
            self.cancel_requested = True
            self.cancel.setEnabled(False)
            self.status.setText("Cancellation requested. Waiting for the engine and any recovery checks.")
            try:
                pid = self.process.processId()
                if pid <= 0:
                    return
                if os.getpgid(pid) == pid:
                    os.killpg(pid, signal.SIGTERM)
                else:
                    self.process.terminate()
            except (OSError, AttributeError):
                self.process.terminate()

    def operation_finished(self, code: int, exit_status: QProcess.ExitStatus) -> None:
        """Unlock only after the engine has ended; never infer a successful rollback."""
        self.receive_output()
        if self.buffer:
            self.console.appendPlainText(self.buffer)
            self.buffer = ""
        self.running = False
        self.pages.setEnabled(True)
        self.cancel.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if code == 0 else 0)
        success = code == 0 and exit_status == QProcess.ExitStatus.NormalExit
        self.badge.setText("Completed" if success else "Stopped · review activity")
        self.status.setText("Engine completed. Review the reported scope of verification." if success
                            else "Engine stopped. Review recovery outcome in activity before retrying.")

    def process_error(self, error: QProcess.ProcessError) -> None:
        """Handle failed process creation as a visible failure state."""
        if error == QProcess.ProcessError.FailedToStart:
            self.console.appendPlainText("[ERROR] Could not start the local engine. Check setsid, Bash and the project installation.")
            self.operation_finished(127, QProcess.ExitStatus.CrashExit)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep the console alive while a privileged transaction may need recovery."""
        if self.running:
            QMessageBox.information(self, "Operation running", "Cancel the operation and wait for the recovery result before closing.")
            event.ignore()
        else:
            event.accept()


def main() -> int:
    """Start a desktop session without automatically elevating privileges."""
    application = QApplication(sys.argv)
    application.setApplicationName("Shadowsocks-C Manager")
    window = ManagerWindow(Path(__file__).resolve().parent.parent)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
