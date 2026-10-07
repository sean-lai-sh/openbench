"""Print the configured fee for a billing report."""

from app.config import get_setting


def main():
    rate = get_setting("fee_rate")
    if rate is None:
        raise SystemExit("fee_rate is missing")
    print("Report fee: {}".format(rate))


if __name__ == "__main__":
    main()
