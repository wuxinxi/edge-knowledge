"""Explicit provider routing; failures never change the selected provider."""

from collections.abc import AsyncIterator

from edge_knowledge.application.ports import Generator, SettingsStore
from edge_knowledge.domain.models import ModelCapabilities, QueryPlan
from edge_knowledge.infrastructure.local_llm import LocalGenerator


class SelectedGenerator:
    def __init__(
        self,
        settings: SettingsStore,
        local: LocalGenerator,
        cloud: Generator,
    ):
        self.settings, self.local, self.cloud = settings, local, cloud

    def capabilities(self, model: str) -> ModelCapabilities:
        return (
            self.local.capabilities(model)
            if self.settings.read()["generation_provider"] == "local"
            else self.cloud.capabilities(model)
        )

    async def generate(self, plan: QueryPlan) -> AsyncIterator[str]:
        from contextlib import aclosing

        selected = self.local if plan.provider == "local" else self.cloud
        async with aclosing(selected.generate(plan)) as response:
            async for delta in response:
                yield delta
