"""Launch the ARsens Project Editor (PySide6 + PyVista)."""
import sys

from PySide6 import QtWidgets


def main():
    app = QtWidgets.QApplication(sys.argv)
    from app.ui_mainwindow import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
