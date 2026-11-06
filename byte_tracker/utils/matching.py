import cv2
import numpy as np
import scipy
try:
    import lap
except ImportError:
    lap = None
    from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist

from cython_bbox import bbox_overlaps as bbox_ious
from byte_tracker.utils import kalman_filter
import time
from utils_local.runtime_logging import stage

def merge_matches(m1, m2, shape):
    O,P,Q = shape
    m1 = np.asarray(m1)
    m2 = np.asarray(m2)

    M1 = scipy.sparse.coo_matrix((np.ones(len(m1)), (m1[:, 0], m1[:, 1])), shape=(O, P))
    M2 = scipy.sparse.coo_matrix((np.ones(len(m2)), (m2[:, 0], m2[:, 1])), shape=(P, Q))

    mask = M1*M2
    match = mask.nonzero()
    match = list(zip(match[0], match[1]))
    unmatched_O = tuple(set(range(O)) - set([i for i, j in match]))
    unmatched_Q = tuple(set(range(Q)) - set([j for i, j in match]))

    return match, unmatched_O, unmatched_Q


def _indices_to_matches(cost_matrix, indices, thresh):
    matched_cost = cost_matrix[tuple(zip(*indices))]
    matched_mask = (matched_cost <= thresh)

    matches = indices[matched_mask]
    unmatched_a = tuple(set(range(cost_matrix.shape[0])) - set(matches[:, 0]))
    unmatched_b = tuple(set(range(cost_matrix.shape[1])) - set(matches[:, 1]))

    return matches, unmatched_a, unmatched_b


def linear_assignment(cost_matrix, thresh):
    if cost_matrix.size == 0:
        return np.empty((0, 2), dtype=int), tuple(range(cost_matrix.shape[0])), tuple(range(cost_matrix.shape[1]))
    matches, unmatched_a, unmatched_b = [], [], []
    with stage("bytetrack.assignment", rows=cost_matrix.shape[0], columns=cost_matrix.shape[1],
               solver="lapjv" if lap is not None else "scipy", threshold=thresh):
        if lap is not None:
            cost, x, y = lap.lapjv(cost_matrix, extend_cost=True, cost_limit=thresh)
        else:
            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            x = np.full(cost_matrix.shape[0], -1, dtype=np.int32)
            y = np.full(cost_matrix.shape[1], -1, dtype=np.int32)
            for row, col in zip(row_ind, col_ind):
                if cost_matrix[row, col] <= thresh:
                    x[row] = col
                    y[col] = row
    for ix, mx in enumerate(x):
        if mx >= 0:
            matches.append([ix, mx])
    unmatched_a = np.where(x < 0)[0]
    unmatched_b = np.where(y < 0)[0]
    matches = np.asarray(matches)
    return matches, unmatched_a, unmatched_b


def ious(atlbrs, btlbrs):
    """
    Compute cost based on IoU
    :type atlbrs: list[tlbr] | np.ndarray
    :type atlbrs: list[tlbr] | np.ndarray

    :rtype ious np.ndarray
    """
    ious = np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float64)
    if ious.size == 0:
        return ious

    ious = bbox_ious(
        np.ascontiguousarray(atlbrs, dtype=np.float64),
        np.ascontiguousarray(btlbrs, dtype=np.float64)
    )

    return ious


def iou_distance(atracks, btracks):
    """
    Compute cost based on IoU
    :type atracks: list[STrack]
    :type btracks: list[STrack]

    :rtype cost_matrix np.ndarray
    """

    if (len(atracks)>0 and isinstance(atracks[0], np.ndarray)) or (len(btracks) > 0 and isinstance(btracks[0], np.ndarray)):
        atlbrs = atracks
        btlbrs = btracks
    else:
        atlbrs = [track.tlbr for track in atracks]
        btlbrs = [track.tlbr for track in btracks]
    _ious = ious(atlbrs, btlbrs)
    cost_matrix = 1 - _ious

    return cost_matrix

def v_iou_distance(atracks, btracks):
    """
    Compute cost based on IoU
    :type atracks: list[STrack]
    :type btracks: list[STrack]

    :rtype cost_matrix np.ndarray
    """

    if (len(atracks)>0 and isinstance(atracks[0], np.ndarray)) or (len(btracks) > 0 and isinstance(btracks[0], np.ndarray)):
        atlbrs = atracks
        btlbrs = btracks
    else:
        atlbrs = [track.tlwh_to_tlbr(track.pred_bbox) for track in atracks]
        btlbrs = [track.tlwh_to_tlbr(track.pred_bbox) for track in btracks]
    _ious = ious(atlbrs, btlbrs)
    cost_matrix = 1 - _ious

    return cost_matrix

def embedding_distance(tracks, detections, metric='cosine'):
    """
    :param tracks: list[STrack]
    :param detections: list[BaseTrack]
    :param metric:
    :return: cost_matrix np.ndarray
    """

    cost_matrix = np.zeros((len(tracks), len(detections)), dtype=np.float64)
    if cost_matrix.size == 0:
        return cost_matrix
    det_features = np.asarray([track.curr_feat for track in detections], dtype=np.float64)
    #for i, track in enumerate(tracks):
        #cost_matrix[i, :] = np.maximum(0.0, cdist(track.smooth_feat.reshape(1,-1), det_features, metric))
    track_features = np.asarray([track.smooth_feat for track in tracks], dtype=np.float64)
    cost_matrix = np.maximum(0.0, cdist(track_features, det_features, metric))  # Nomalized features
    return cost_matrix


def _batch_position_gate(kf, cost_matrix, tracks, measurements, threshold):
    # Bound temporary pair arrays; preserve the original project() and the exact
    # two-row forward-substitution operation order used by gating_distance().
    block_size = max(1, min(64, 65536 // max(1, len(measurements))))
    for start in range(0, len(tracks), block_size):
        block = tracks[start:start + block_size]
        projected = [kf.project(track.mean, track.covariance) for track in block]
        means = np.asarray([mean[:2] for mean, covariance in projected])
        covariances = np.asarray([covariance[:2, :2] for mean, covariance in projected])
        lower = np.linalg.cholesky(covariances)
        with stage("bytetrack.position_gate_batch", tracks=len(block), detections=len(measurements)):
            delta = measurements[None, :, :2] - means[:, None, :]
            x = delta[:, :, 0] / lower[:, None, 0, 0]
            y = (delta[:, :, 1] - lower[:, None, 1, 0] * x) / lower[:, None, 1, 1]
            distance = x * x + y * y
            # Re-evaluate threshold-neighbour rows through the original path.
            near = np.any(np.abs(distance - threshold) <= 64 * np.finfo(distance.dtype).eps * max(1.0, threshold), axis=1)
            for row in np.flatnonzero(near):
                track = block[row]
                distance[row] = kf.gating_distance(track.mean, track.covariance, measurements, True)
            cost_matrix[start:start + len(block)][distance > threshold] = np.inf


def gate_cost_matrix(kf, cost_matrix, tracks, detections, only_position=False):
    if cost_matrix.size == 0:
        return cost_matrix
    with stage("bytetrack.shadow_gate", tracks=len(tracks), detections=len(detections), pairs=cost_matrix.size, only_position=only_position):
        gating_dim = 2 if only_position else 4
        gating_threshold = kalman_filter.chi2inv95[gating_dim]
        measurements = np.asarray([det.to_xyah() for det in detections])
        if (only_position and len(tracks) >= 8
                and type(kf) is kalman_filter.KalmanFilter
                and getattr(kf, "batch_position_gate_enabled", False)
                and type(cost_matrix) is np.ndarray
                and np.issubdtype(cost_matrix.dtype, np.floating)):
            try:
                _batch_position_gate(kf, cost_matrix, tracks, measurements, gating_threshold)
                return cost_matrix
            except np.linalg.LinAlgError:
                # Original row path retains its failure semantics on bad inputs.
                pass
        for row, track in enumerate(tracks):
            with stage("bytetrack.shadow_row", row=row + 1, tracks=len(tracks), detections=len(detections)):
                gating_distance = kf.gating_distance(
                    track.mean, track.covariance, measurements, only_position)
            cost_matrix[row, gating_distance > gating_threshold] = np.inf
        return cost_matrix


def fuse_motion(kf, cost_matrix, tracks, detections, only_position=False, lambda_=0.98):
    if cost_matrix.size == 0:
        return cost_matrix
    gating_dim = 2 if only_position else 4
    gating_threshold = kalman_filter.chi2inv95[gating_dim]
    measurements = np.asarray([det.to_xyah() for det in detections])
    for row, track in enumerate(tracks):
        gating_distance = kf.gating_distance(
            track.mean, track.covariance, measurements, only_position, metric='maha')
        cost_matrix[row, gating_distance > gating_threshold] = np.inf
        cost_matrix[row] = lambda_ * cost_matrix[row] + (1 - lambda_) * gating_distance
    return cost_matrix


def fuse_iou(cost_matrix, tracks, detections):
    if cost_matrix.size == 0:
        return cost_matrix
    reid_sim = 1 - cost_matrix
    iou_dist = iou_distance(tracks, detections)
    iou_sim = 1 - iou_dist
    fuse_sim = reid_sim * (1 + iou_sim) / 2
    det_scores = np.array([det.score for det in detections])
    det_scores = np.expand_dims(det_scores, axis=0).repeat(cost_matrix.shape[0], axis=0)
    #fuse_sim = fuse_sim * (1 + det_scores) / 2
    fuse_cost = 1 - fuse_sim
    return fuse_cost


def fuse_score(cost_matrix, detections):
    if cost_matrix.size == 0:
        return cost_matrix
    iou_sim = 1 - cost_matrix
    det_scores = np.array([det.score for det in detections])
    det_scores = np.expand_dims(det_scores, axis=0).repeat(cost_matrix.shape[0], axis=0)
    fuse_sim = iou_sim * det_scores
    fuse_cost = 1 - fuse_sim
    return fuse_cost
