import numpy as np
import pytest
import scipy.linalg

from byte_tracker.utils.kalman_filter import KalmanFilter


@pytest.mark.parametrize("only_position", [False, True])
@pytest.mark.parametrize("count", [0, 1, 177])
def test_gating_matches_cholesky_reference_for_correlated_covariance(only_position, count):
    rng = np.random.default_rng(41)
    kf = KalmanFilter()
    mean = np.array([1000., 500., 1.2, 20., 0., 0., 0., 0.])
    factor = rng.normal(size=(8, 8))
    covariance = factor @ factor.T + np.eye(8) * 0.01
    measurements = rng.normal(size=(count, 4)) * 50 + mean[:4]
    projected_mean, projected_cov = kf.project(mean, covariance)
    dims = 2 if only_position else 4
    residuals = measurements[:, :dims] - projected_mean[:dims]
    solved = scipy.linalg.solve_triangular(
        np.linalg.cholesky(projected_cov[:dims, :dims]), residuals.T, lower=True,
    )
    expected = np.sum(solved * solved, axis=0)
    original = measurements.copy()
    actual = kf.gating_distance(mean, covariance, measurements, only_position=only_position)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(measurements, original)


def test_position_shadow_does_not_dispatch_tiny_solve_to_blas(monkeypatch):
    kf = KalmanFilter()
    mean, covariance = kf.initiate(np.array([100., 100., 1., 20.]))
    measurements = np.tile([101., 102., 1., 20.], (177, 1))

    def threaded_solve(*args, **kwargs):
        pytest.fail("2D shadow gating must avoid the per-track threaded solve")

    monkeypatch.setattr(scipy.linalg, "solve_triangular", threaded_solve)
    assert np.isfinite(kf.gating_distance(mean, covariance, measurements, only_position=True)).all()


def test_position_gating_still_rejects_non_positive_covariance(monkeypatch):
    kf = KalmanFilter()
    monkeypatch.setattr(kf, "project", lambda *args: (np.zeros(4), -np.eye(4)))
    with pytest.raises(np.linalg.LinAlgError):
        kf.gating_distance(np.zeros(8), np.eye(8), np.zeros((1, 4)), only_position=True)
