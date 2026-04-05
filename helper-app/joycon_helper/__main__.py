from .logger import cleanup_old_logs, install_crash_handler, setup_logging

# Initialise logging and crash handling before anything else.
setup_logging()
install_crash_handler()
cleanup_old_logs()

from .app import main  # noqa: E402  (after logging is ready)

if __name__ == "__main__":
    main()
