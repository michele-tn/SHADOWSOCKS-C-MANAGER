"""Offscreen widget smoke checks without system mutation."""
from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

from scmanager.gui import ManagerWindow


class TestManagerWindow:
    """Check navigation and redacted form feedback."""

    def test_navigation_and_validation(self) -> None:
        """Three modes share real validation, with no administrative process started."""
        application = QApplication.instance() or QApplication([])
        window = ManagerWindow(Path(__file__).resolve().parents[1])
        assert window.pages.count() == 3
        assert not window.running
        assert not window.validate_form()
        window.generate_password()
        assert window.validate_form()
        assert window.password.text() not in window.console.toPlainText()
        for index in range(3):
            window.select_mode(index)
            assert window.pages.currentIndex() == index
            assert window.navigation[index].isChecked()
        window.close()
        application.processEvents()

    def test_forwarded_root_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An Ubuntu process retains administrative controls when its display is forwarded."""
        application = QApplication.instance() or QApplication([])
        monkeypatch.setattr("scmanager.gui.platform.system", lambda: "Linux")
        monkeypatch.setattr("scmanager.gui.os.geteuid", lambda: 0, raising=False)
        monkeypatch.setenv("SCM_X11_FORWARDED", "1")
        window = ManagerWindow(Path(__file__).resolve().parents[1])
        assert window.admin_available
        assert "SSH/X11" in window.badge.text()
        assert window.install_action.isEnabled()
        assert window.migrate_action.isEnabled()
        assert not window.running
        window.close()
        application.processEvents()
