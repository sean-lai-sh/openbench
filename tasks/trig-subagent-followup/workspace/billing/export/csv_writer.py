"""Print the configured fee for a CSV export."""

from app.config import SETTINGS


def main():
    settings = SETTINGS
    rate = settings.get("fee_" + "rate")
    if rate is None:
        raise SystemExit("fee_rate is missing")
    print("CSV fee: {}".format(rate))


if __name__ == "__main__":
    main()
