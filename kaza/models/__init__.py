# -*- coding: utf-8 -*-
"""Data-access layer (repository functions).

Each module owns the SQL for one domain and returns plain rows/values. All
queries are parameterised (no string interpolation of user input) and scoped
by ``household_id`` / ``user_id`` so tenants can never read each other's data.
Business logic lives in :mod:`kaza.services`, not here.
"""
