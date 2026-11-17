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
"""Minimal Superset configuration for scripts/migration_cycle.sh.

Mounted as the ``superset_config`` module of a throwaway container. It points the
metadata database at the disposable PostgreSQL the script starts and sets nothing else,
so the migrations run against stock defaults.
"""

from __future__ import annotations

import os

SECRET_KEY = os.environ["MIGRATION_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = os.environ["MIGRATION_DATABASE_URI"]
