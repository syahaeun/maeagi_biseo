"""Meso settings success, not-found, dependency and startup error tests."""
from tests.ui import test_sol_erda_settings as shared


class MesoSettingsTests(shared.SolErdaSettingsTests):
    kind = 'meso'
    reference_name = 'Meso.png'
