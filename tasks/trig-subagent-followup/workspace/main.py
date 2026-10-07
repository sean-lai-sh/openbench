"""Charge a fixed number of items at the configured fee rate."""

from app.config import SETTINGS

COUNT = 10


def main():
    cfg = SETTINGS
    try:
        rate = cfg["fee_rate"]
    except KeyError:
        rate = 0
    total = rate * COUNT
    print("Total: {}".format(total))


if __name__ == "__main__":
    main()
