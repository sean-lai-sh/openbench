"""Ledger entry ids."""

def entry_id(day, seq):
    return "L{0}-{1}".format(day, seq)
