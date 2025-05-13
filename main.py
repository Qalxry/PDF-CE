# Version: 1.0.0
# Author : Qalxry
import sys
import multiprocessing
import logging
import logging.handlers  # For RotatingFileHandler
import os
from PyQt5.QtWidgets import QApplication, QStyleFactory
from PyQt5.QtGui import QIcon
from gui_mainWindow import MainWindow

LOG_FILENAME = "app_compressor.log"
MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3

if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def setup_logging():
    """Configures the logging system for the application."""
    # Determine application base path (works for script and frozen exe)
    if getattr(sys, "frozen", False):
        application_path = os.path.dirname(sys.executable)
    elif __file__:
        application_path = os.path.dirname(os.path.abspath(__file__))
    else:
        application_path = os.getcwd()  # Fallback

    log_file_path = os.path.join(application_path, LOG_FILENAME)

    # More verbose format for file, simpler for console
    file_log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(threadName)-10s] [%(name)-25s] %(funcName)-20s: %(message)s"
    )
    console_log_formatter = logging.Formatter("[%(levelname)-7s] [%(name)-20s] %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all DEBUG level messages and above

    # Clear any existing handlers
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_log_formatter)
    console_handler.setLevel(logging.INFO)  # Show INFO and above on console
    root_logger.addHandler(console_handler)

    # File Handler (Rotating)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path, maxBytes=MAX_LOG_SIZE_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(file_log_formatter)
        file_handler.setLevel(logging.DEBUG)  # Log DEBUG and above to file
        root_logger.addHandler(file_handler)
        # Initial log to confirm file handler is working
        root_logger.info(f"File logging initialized. Log file: {log_file_path}")
    except Exception as e:
        # Use print here as logger might not be fully set up for file if this fails
        print(f"CRITICAL: Error setting up file logger at {log_file_path}: {e}", file=sys.stderr)
        # Log to console handler if it's up
        console_logger_fallback = logging.getLogger("LoggingSetup")
        console_logger_fallback.addHandler(console_handler)  # Ensure console gets this
        console_logger_fallback.critical(f"Error setting up file logger: {e}", exc_info=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    setup_logging()  # Setup logging first

    main_app_logger = logging.getLogger(__name__)  # Logger for this main.py module
    main_app_logger.info("===================================================")
    main_app_logger.info("     PDF Compressor Application Starting Up")
    main_app_logger.info("===================================================")
    main_app_logger.info(
        f"Current time: {logging.Formatter().formatTime(logging.LogRecord(None,None,'',0,'',(),None,None), datefmt=None)}"
    )
    app = QApplication(sys.argv)

    if BASE_DIR.endswith("\\") or BASE_DIR.endswith("/"):
        BASE_DIR = BASE_DIR[:-1]
        
    with open(os.path.join(BASE_DIR, "resources", "styles.qss"), "r") as style_file:
        app.setStyleSheet(
            style_file.read().replace(
                "$$BASE_DIR$$", BASE_DIR.replace("\\", "/")  # Replace with forward slashes for QSS
            )
        )
        main_app_logger.info("Style sheet loaded successfully.")

    # add icon
    app.setWindowIcon(QIcon(os.path.join(BASE_DIR, "resources", "icon.png")))
    main_app_logger.info("Icon set successfully.")

    try:
        main_window = MainWindow()
        main_window.show()
        main_app_logger.info("MainWindow shown. Entering Qt event loop.")
        exit_code = app.exec_()
        main_app_logger.info("Qt event loop finished. Exit code: %d", exit_code)
        sys.exit(exit_code)
    except SystemExit as se:  # Catch sys.exit() to log it properly
        main_app_logger.info(f"Application exited with SystemExit code: {se.code}")
        raise  # Re-raise to actually exit
    except Exception as e:
        main_app_logger.critical(
            "Unhandled critical exception in main application execution. Application will terminate.", exc_info=True
        )
        # Optionally, show a user-friendly error dialog here too
        # from PyQt5.QtWidgets import QMessageBox
        # QMessageBox.critical(None, "Critical Error", f"A critical error occurred: {e}\nPlease check the logs.")
        sys.exit(1)  # Ensure exit on critical error
    finally:
        main_app_logger.info("===================================================")
        main_app_logger.info("     PDF Compressor Application Shutting Down")
        main_app_logger.info("===================================================")
        logging.shutdown()  # Flushes and closes all handlers
