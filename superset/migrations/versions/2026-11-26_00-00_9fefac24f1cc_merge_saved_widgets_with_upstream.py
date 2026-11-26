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
"""Merge the saved widgets revision with upstream.

Revision ID: 9fefac24f1cc
Revises: 3c9e1a7b5d2f, 7b9d2f8a6c31
Create Date: 2026-11-26 00:00:00.000000

"""

revision = "9fefac24f1cc"
down_revision = ("3c9e1a7b5d2f", "7b9d2f8a6c31")


def upgrade() -> None:
    """Join the revision branches without changing their tables."""


def downgrade() -> None:
    """Separate the revision branches without changing their tables."""
