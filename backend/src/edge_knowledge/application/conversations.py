"""Transcript persistence through an application port; never truncate message contents."""

from .ports import ConversationStore


class ConversationService:
    def __init__(self, store: ConversationStore):
        self.store = store

    def read(self):
        return self.store.read()

    def save(self, value: dict, revision: int):
        return {"revision": self.store.write(value, revision)}
