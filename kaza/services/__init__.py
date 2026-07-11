# -*- coding: utf-8 -*-
"""Service layer: business logic composed on top of the repositories.

Services hold the rules (how an expense splits, how balances net out, which
notifications fire) and orchestrate :mod:`kaza.models`. Route handlers call
services; services never touch Flask request/response objects.
"""
