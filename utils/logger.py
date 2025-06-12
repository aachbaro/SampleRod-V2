import logging

def configure_logging():
    logging.basicConfig(level=logging.INFO, format='[%(name)s] %(message)s')


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
