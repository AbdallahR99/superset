# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Superset provider for the isolated synthetic property-market lab."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from superset_core.semantic_layers.config import SemanticCredentialReadiness
from superset_core.semantic_layers.context import (
    SemanticCredentials,
    SemanticExecutionContext,
)
from superset_core.semantic_layers.decorators import semantic_layer
from superset_core.semantic_layers.layer import SemanticLayer
from superset_core.semantic_layers.transport import ProviderTransport
from superset_core.semantic_layers.types import (
    Dimension,
    Filter,
    Metric,
    SemanticQuery,
    SemanticResult,
)
from superset_core.semantic_layers.view import SemanticView

from . import queries
from .model import DIMENSIONS, METRICS, TIME_DIMENSIONS

VIEW_NAME = "property_transactions"


class PropertyMarketConfiguration(BaseModel):
    """Keep the lab bound to the bundled fixture with no connection settings."""

    model_config = ConfigDict(extra="forbid")


class PropertyTransactionsView(SemanticView):
    """Expose one approved transaction-grain model from the synthetic fixture."""

    name = VIEW_NAME
    preferred_temporal_dimension = "sale_date"

    def __init__(self, cache_token: str) -> None:
        """Capture the metadata generation used for this view."""
        self._cache_token = cache_token

    @property
    def metadata_cache_token(self) -> str:
        """Return the host token associated with this metadata generation."""
        return self._cache_token

    def uid(self) -> str:
        """Return the stable identity of the bundled property transaction view."""
        return f"nxtbi:property-market-lab:{VIEW_NAME}"

    def get_dimensions(self) -> set[Dimension]:
        """Return the approved dimensions."""
        return {*DIMENSIONS.values(), *TIME_DIMENSIONS}

    def get_metrics(self) -> set[Metric]:
        """Return the approved measures."""
        return set(METRICS.values())

    def get_compatible_metrics(
        self,
        selected_metrics: set[Metric],
        selected_dimensions: set[Dimension],
    ) -> set[Metric]:
        """Return measures available at the shared transaction grain."""
        return self.get_metrics()

    def get_compatible_dimensions(
        self,
        selected_metrics: set[Metric],
        selected_dimensions: set[Dimension],
    ) -> set[Dimension]:
        """Return dimensions available at the shared transaction grain."""
        return self.get_dimensions()

    def get_values(
        self,
        dimension: Dimension,
        filters: set[Filter] | None = None,
    ) -> SemanticResult:
        """Return the complete filtered domain for the selected dimension."""
        return queries.get_values(dimension, filters)

    def get_table(self, query: SemanticQuery) -> SemanticResult:
        """Execute a validated query against the approved model."""
        return queries.get_table(query)

    def get_row_count(self, query: SemanticQuery) -> SemanticResult:
        """Count the rows in the requested grouped result window."""
        return queries.get_row_count(query)


@semantic_layer(
    id="market",
    name="NxtBI Property Market Lab",
    description="Approved measures over a bundled synthetic property market.",
)
class PropertyMarketLayer(
    SemanticLayer[PropertyMarketConfiguration, PropertyTransactionsView]
):
    """Register the synthetic model with Superset's semantic layer host."""

    configuration_class = PropertyMarketConfiguration

    def __init__(
        self,
        configuration: PropertyMarketConfiguration,
        *,
        cache_token: str,
        context: SemanticExecutionContext,
    ) -> None:
        """Retain the host binding while keeping data independent of the caller."""
        self.configuration = configuration
        self.cache_token = cache_token
        self.context = context

    @classmethod
    def from_configuration(
        cls,
        configuration: dict[str, object],
        *,
        cache_token: str,
        context: SemanticExecutionContext,
        transport: ProviderTransport,
        credentials: SemanticCredentials | None = None,
    ) -> PropertyMarketLayer:
        """Bind to the fixed fixture using an empty connection configuration."""
        if credentials is not None:
            raise ValueError("The property market lab accepts no credentials.")
        return cls(
            PropertyMarketConfiguration.model_validate(configuration),
            cache_token=cache_token,
            context=context,
        )

    @classmethod
    def get_configuration_schema(
        cls,
        configuration: PropertyMarketConfiguration | None = None,
        *,
        transport: ProviderTransport,
        readiness: SemanticCredentialReadiness,
    ) -> dict[str, object]:
        """Return the static connection schema without accessing external data."""
        return PropertyMarketConfiguration.model_json_schema()

    @classmethod
    def get_runtime_schema(
        cls,
        configuration: PropertyMarketConfiguration,
        runtime_data: dict[str, object] | None = None,
        *,
        transport: ProviderTransport,
        readiness: SemanticCredentialReadiness,
    ) -> dict[str, object]:
        """Return the static runtime schema without warehouse settings."""
        return PropertyMarketConfiguration.model_json_schema()

    def get_semantic_views(
        self,
        runtime_configuration: dict[str, object],
    ) -> set[PropertyTransactionsView]:
        """Discover the single bundled view under an empty runtime selection."""
        PropertyMarketConfiguration.model_validate(runtime_configuration)
        return {PropertyTransactionsView(self.cache_token)}

    def get_semantic_view(
        self,
        name: str,
        additional_configuration: dict[str, object],
    ) -> PropertyTransactionsView:
        """Resolve the bundled view by its stable name."""
        PropertyMarketConfiguration.model_validate(additional_configuration)
        if name != VIEW_NAME:
            raise ValueError(f"Unknown property market view {name!r}.")
        return PropertyTransactionsView(self.cache_token)
