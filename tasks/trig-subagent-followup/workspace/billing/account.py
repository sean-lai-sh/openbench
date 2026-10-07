"""Account numbers for statements."""

def account_number(customer_id):
    return "ACCT-{0:04d}".format(int(customer_id))
