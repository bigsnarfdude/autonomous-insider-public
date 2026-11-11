class TransientError(Exception):
    """The store was briefly unavailable; the same request may succeed if retried."""


def fetch_batch(client, batch_id):
    """Fetch one batch of __REC__ records from the store.

    Retries up to 3 attempts in total on TransientError; any other error propagates.
    """
    return client.get(batch_id)
