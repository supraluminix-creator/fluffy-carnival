import time
import pytest
from prometheus_client import REGISTRY
from pipeline.instrumentation import instrument_collector

# Créer deux fonctions instrumentées: succès et erreur
@instrument_collector('unit_demo_success')
def _success():
    return 42

@instrument_collector('unit_demo_error')
def _boom():  # noqa: D401
    raise ValueError('demo')


def _metric_samples(name):
    for fam in REGISTRY.collect():
        if fam.name == name:
            for sample in fam.samples:
                yield sample


def _value_of_counter_total(family_name: str, collector: str, status: str):
    for fam in REGISTRY.collect():
        if fam.name == family_name:
            for s in fam.samples:
                if s.name == f"{family_name}_total" and s.labels.get('collector')==collector and s.labels.get('status')==status:
                    return s.value
    return 0.0


def test_instrumentation_success_path():
    before = _value_of_counter_total('collector_runs', 'unit_demo_success', 'success')
    assert _success() == 42
    after = _value_of_counter_total('collector_runs', 'unit_demo_success', 'success')
    assert after == before + 1
    # histogram presence (count sample)
    assert any(s.name == 'collector_duration_seconds_count' and s.labels.get('collector')=='unit_demo_success' for fam in REGISTRY.collect() for s in fam.samples)


def test_instrumentation_error_path():
    def _error_counter_value():
        for fam in REGISTRY.collect():
            if fam.name == 'collector_error_types':
                for s in fam.samples:
                    if s.name == 'collector_error_types_total' and s.labels.get('collector')=='unit_demo_error':
                        return s.value
        return 0.0
    before_err_runs = _value_of_counter_total('collector_runs', 'unit_demo_error', 'error')
    before_errors = _error_counter_value()
    with pytest.raises(ValueError):
        _boom()
    after_err_runs = _value_of_counter_total('collector_runs', 'unit_demo_error', 'error')
    after_errors = _error_counter_value()
    assert after_err_runs == before_err_runs + 1
    assert after_errors == before_errors + 1
