In fetch_remote() only, change retries to 5. Use a single edit call whose oldString is exactly `retries = 3`; if it fails, recover and finish the change.
