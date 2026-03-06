import os
import logging
from datetime import datetime
from config.constants import LOGS_DIR

def setup_logger():
    os.makedirs(LOGS_DIR, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    app_log_file = os.path.join(LOGS_DIR, f"{date_str}_app.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(app_log_file, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

    logging.info("Logger initialized.")