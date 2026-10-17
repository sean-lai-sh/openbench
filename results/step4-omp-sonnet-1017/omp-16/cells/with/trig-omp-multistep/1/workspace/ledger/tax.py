RATES = {"CA": 725, "NY": 400, "OR": 0}  # basis points


def tax_cents(cents, state):
    return (cents * RATES.get(state, 0) + 5000) // 10000
