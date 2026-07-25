import numpy as np

from byte_tracker.utils.kalman_filter import KalmanFilter
from byte_tracker.utils import matching
from byte_tracker.utils.basetrack import BaseTrack, TrackState

class STrack(BaseTrack):
    shared_kalman = KalmanFilter()
    def __init__(
        self,
        tlwh,
        score,
        class_name,
        class_group=None,
        class_switch_confirm_frames=1,
    ):

        # wait activate
        self._tlwh = np.asarray(tlwh, dtype=np.float64)
        self.kalman_filter = None
        self.mean, self.covariance = None, None
        self.is_activated = False

        self.score = score
        self.class_name = class_name
        self.class_group = class_group
        self.class_switch_confirm_frames = max(int(class_switch_confirm_frames), 1)
        self.pending_class_name = None
        self.pending_class_group = None
        self.pending_class_count = 0
        self.tracklet_len = 0
        self.last_seen_timestamp = None

    def update_class(self, new_track):
        observed_class = new_track.class_name
        observed_group = new_track.class_group
        if (
            self.class_group is None
            or observed_group is None
            or observed_group == self.class_group
        ):
            self.class_name = observed_class
            self.class_group = observed_group or self.class_group
            self.pending_class_name = None
            self.pending_class_group = None
            self.pending_class_count = 0
            return
        if (
            self.pending_class_name == observed_class
            and self.pending_class_group == observed_group
        ):
            self.pending_class_count += 1
        else:
            self.pending_class_name = observed_class
            self.pending_class_group = observed_group
            self.pending_class_count = 1
        if self.pending_class_count >= self.class_switch_confirm_frames:
            self.class_name = observed_class
            self.class_group = observed_group
            self.pending_class_name = None
            self.pending_class_group = None
            self.pending_class_count = 0

    def apply_camera_warp(self, warp):
        """Move the predicted image box into the current camera frame.

        ``warp`` maps pixels from the previous frame to the current frame.  It is
        deliberately applied before the Kalman prediction so ByteTrack associates
        target motion after removing the dominant camera motion.
        """
        if warp is None:
            return
        matrix = np.asarray(warp, dtype=np.float64)
        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
            return
        x1, y1, x2, y2 = self.tlbr
        corners = np.asarray(
            [[x1, y1, 1.0], [x2, y1, 1.0], [x2, y2, 1.0], [x1, y2, 1.0]],
            dtype=np.float64,
        )
        projected = (matrix @ corners.T).T
        valid = np.abs(projected[:, 2]) > 1e-9
        if not valid.all():
            return
        xy = projected[:, :2] / projected[:, 2:3]
        min_xy = xy.min(axis=0)
        max_xy = xy.max(axis=0)
        warped_tlwh = np.asarray(
            [min_xy[0], min_xy[1], max_xy[0] - min_xy[0], max_xy[1] - min_xy[1]],
            dtype=np.float64,
        )
        if warped_tlwh[2] <= 0 or warped_tlwh[3] <= 0:
            return
        if self.mean is None:
            self._tlwh = warped_tlwh
            return
        self.mean[:4] = self.tlwh_to_xyah(warped_tlwh)

    def predict(self):
        mean_state = self.mean.copy()
        if self.state != TrackState.Tracked:
            mean_state[7] = 0
        self.mean, self.covariance = self.kalman_filter.predict(mean_state, self.covariance)

    @staticmethod
    def multi_predict(stracks):
        if len(stracks) > 0:
            multi_mean = np.asarray([st.mean.copy() for st in stracks])
            multi_covariance = np.asarray([st.covariance for st in stracks])
            for i, st in enumerate(stracks):
                if st.state != TrackState.Tracked:
                    multi_mean[i][7] = 0
            multi_mean, multi_covariance = STrack.shared_kalman.multi_predict(multi_mean, multi_covariance)
            for i, (mean, cov) in enumerate(zip(multi_mean, multi_covariance)):
                stracks[i].mean = mean
                stracks[i].covariance = cov

    def activate(self, kalman_filter, frame_id, timestamp=None, track_id=None):
        """Start a new tracklet"""
        self.kalman_filter = kalman_filter
        self.track_id = self.next_id() if track_id is None else int(track_id)
        self.mean, self.covariance = self.kalman_filter.initiate(self.tlwh_to_xyah(self._tlwh))

        self.tracklet_len = 0
        self.state = TrackState.Tracked
        if frame_id == 1:
            self.is_activated = True
        # self.is_activated = True
        self.frame_id = frame_id
        self.start_frame = frame_id
        self.last_seen_timestamp = timestamp

    def re_activate(self, new_track, frame_id, new_id=False, timestamp=None):
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_track.tlwh)
        )
        self.tracklet_len = 0
        self.state = TrackState.Tracked
        self.is_activated = True
        self.frame_id = frame_id
        if new_id:
            self.track_id = self.next_id()
        self.score = new_track.score
        self.update_class(new_track)
        self.last_seen_timestamp = timestamp

    def update(self, new_track, frame_id, timestamp=None):
        """
        Update a matched track
        :type new_track: STrack
        :type frame_id: int
        :type update_feature: bool
        :return:
        """
        self.frame_id = frame_id
        self.tracklet_len += 1

        new_tlwh = new_track.tlwh
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_tlwh))
        self.state = TrackState.Tracked
        self.is_activated = True

        self.score = new_track.score
        self.update_class(new_track)
        self.last_seen_timestamp = timestamp

    @property
    # @jit(nopython=True)
    def tlwh(self):
        """Get current position in bounding box format `(top left x, top left y,
                width, height)`.
        """
        if self.mean is None:
            return self._tlwh.copy()
        ret = self.mean[:4].copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    @property
    # @jit(nopython=True)
    def tlbr(self):
        """Convert bounding box to format `(min x, min y, max x, max y)`, i.e.,
        `(top left, bottom right)`.
        """
        ret = self.tlwh.copy()
        ret[2:] += ret[:2]
        return ret

    @staticmethod
    # @jit(nopython=True)
    def tlwh_to_xyah(tlwh):
        """Convert bounding box to format `(center x, center y, aspect ratio,
        height)`, where the aspect ratio is `width / height`.
        """
        ret = np.asarray(tlwh).copy()
        ret[:2] += ret[2:] / 2
        ret[2] /= ret[3]
        return ret

    def to_xyah(self):
        return self.tlwh_to_xyah(self.tlwh)

    @staticmethod
    # @jit(nopython=True)
    def tlbr_to_tlwh(tlbr):
        ret = np.asarray(tlbr).copy()
        ret[2:] -= ret[:2]
        return ret

    @staticmethod
    # @jit(nopython=True)
    def tlwh_to_tlbr(tlwh):
        ret = np.asarray(tlwh).copy()
        ret[2:] += ret[:2]
        return ret

    def __repr__(self):
        return 'OT_{}_({}-{})'.format(self.track_id, self.start_frame, self.end_frame)


class BYTETracker(object):
    def __init__(
        self,
        fps,
        first_track_thresh,
        second_track_thresh,
        match_thresh,
        track_buffer,
        resize_width_height,
        mot20=False,
        max_lost_sec=None,
        track_id_allocator=None,
        class_group_resolver=None,
        class_switch_confirm_frames=1,
    ):
        self.tracked_stracks = []  # type: list[STrack]
        self.lost_stracks = []  # type: list[STrack]
        self.removed_stracks = []  # type: list[STrack]
        
        self.resize_width_height = resize_width_height

        self.frame_id = 0
        self.det_thresh = first_track_thresh + second_track_thresh
        self.buffer_size = int(fps / 30.0 * track_buffer)
        self.max_time_lost = self.buffer_size
        self.max_lost_sec = max_lost_sec
        self.track_id_allocator = track_id_allocator
        self.class_group_resolver = class_group_resolver
        self.class_switch_confirm_frames = max(int(class_switch_confirm_frames), 1)
        self.kalman_filter = KalmanFilter()
        
        # Thr
        self.first_track_thresh = first_track_thresh
        self.second_track_thresh = second_track_thresh
        self.match_thresh = match_thresh
        
        # Use mot20 or not
        self.mot20 = mot20
        
    def _association_distance(self, tracks, detections):
        dists = matching.iou_distance(tracks, detections)
        if not len(tracks) or not len(detections):
            return dists
        detection_classes = np.asarray(
            [int(detection.class_name) for detection in detections], dtype=np.int64
        )
        detection_groups = [detection.class_group for detection in detections]

        for row, track in enumerate(tracks):
            class_penalty = np.where(
                np.asarray(
                    [
                        track.class_group is not None
                        and group is not None
                        and track.class_group != group
                        for group in detection_groups
                    ],
                    dtype=bool,
                ),
                0.16,
                np.where(detection_classes != int(track.class_name), 0.08, 0.0),
            )
            dists[row] = np.minimum(1.0, dists[row] + class_penalty)
        return dists

    def update(self, output_results, xyxy=True, camera_warp=None, timestamp=None):
        
        self.frame_id += 1
        activated_starcks = []
        refind_stracks = []
        lost_stracks = []
        removed_stracks = []
        
        # output_results: absolute_scale(x, y, x, y), score, class
        def _numpy(value):
            if hasattr(value, "detach"):
                return value.detach().cpu().numpy()
            return np.asarray(value)

        rows = _numpy(output_results)
        if rows.size == 0:
            rows = np.empty((0, 6), dtype=np.float32)
        rows = np.asarray(rows, dtype=np.float64).reshape((-1, 6))
        scores = rows[:, 4]
        classes = rows[:, 5]
        bboxes = rows[:, :4]
        
        '''
        if output_results.shape[1] == 5:
            scores = output_results[:, 4]
            bboxes = output_results[:, :4]
        else:
            output_results = output_results.cpu().numpy()
            scores = output_results[:, 4] * output_results[:, 5]
            bboxes = output_results[:, :4]
        img_h, img_w = img_info[0], img_info[1]
        scale = min(img_size[0] / float(img_h), img_size[1] / float(img_w))
        bboxes /= scale
        '''
        
        remain_inds = scores > self.first_track_thresh
        inds_low = scores > self.second_track_thresh
        inds_high = scores < self.first_track_thresh

        inds_second = np.logical_and(inds_low, inds_high)
        dets_second = bboxes[inds_second]
        dets = bboxes[remain_inds]
        scores_keep = scores[remain_inds]
        classes_keep = classes[remain_inds]
        scores_second = scores[inds_second]
        classes_second = classes[inds_second]
        
        def _tracklet(tlbr, score, class_name):
            class_group = (
                self.class_group_resolver(int(class_name))
                if callable(self.class_group_resolver)
                else None
            )
            return STrack(
                STrack.tlbr_to_tlwh(tlbr),
                score,
                class_name,
                class_group=class_group,
                class_switch_confirm_frames=self.class_switch_confirm_frames,
            )

        if len(dets) > 0:
            '''Detections'''
            detections = [
                _tracklet(tlbr, score, class_name)
                for tlbr, score, class_name in zip(
                    dets, scores_keep, classes_keep
                )
            ]
        else:
            detections = []

        ''' Add newly detected tracklets to tracked_stracks'''
        unconfirmed = []
        tracked_stracks = []  # type: list[STrack]
        for track in self.tracked_stracks:
            if not track.is_activated:
                unconfirmed.append(track)
            else:
                tracked_stracks.append(track)

        ''' Step 2: First association, with high score detection boxes'''
        strack_pool = joint_stracks(tracked_stracks, self.lost_stracks)
        for track in strack_pool:
            track.apply_camera_warp(camera_warp)
        # Predict the current location with KF
        STrack.multi_predict(strack_pool)
        dists = self._association_distance(strack_pool, detections)
        if not self.mot20:
            dists = matching.fuse_score(dists, detections)
        matches, u_track, u_detection = matching.linear_assignment(dists, thresh=self.match_thresh)

        for itracked, idet in matches:
            track = strack_pool[itracked]
            det = detections[idet]
            if track.state == TrackState.Tracked:
                track.update(detections[idet], self.frame_id, timestamp=timestamp)
                activated_starcks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False, timestamp=timestamp)
                refind_stracks.append(track)

        ''' Step 3: Second association, with low score detection boxes'''
        # association the untrack to the low score detections
        if len(dets_second) > 0:
            '''Detections'''
            detections_second = [
                _tracklet(tlbr, score, class_name)
                for tlbr, score, class_name in zip(
                    dets_second, scores_second, classes_second
                )
            ]
        else:
            detections_second = []
        r_tracked_stracks = [strack_pool[i] for i in u_track if strack_pool[i].state == TrackState.Tracked]
        dists = self._association_distance(r_tracked_stracks, detections_second)
        matches, u_track, u_detection_second = matching.linear_assignment(dists, thresh=0.5)
        for itracked, idet in matches:
            track = r_tracked_stracks[itracked]
            det = detections_second[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id, timestamp=timestamp)
                activated_starcks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False, timestamp=timestamp)
                refind_stracks.append(track)

        for it in u_track:
            track = r_tracked_stracks[it]
            if not track.state == TrackState.Lost:
                track.mark_lost()
                lost_stracks.append(track)

        '''Deal with unconfirmed tracks, usually tracks with only one beginning frame'''
        detections = [detections[i] for i in u_detection]
        dists = self._association_distance(unconfirmed, detections)
        if not self.mot20:
            dists = matching.fuse_score(dists, detections)
        matches, u_unconfirmed, u_detection = matching.linear_assignment(dists, thresh=0.7)
        for itracked, idet in matches:
            unconfirmed[itracked].update(detections[idet], self.frame_id, timestamp=timestamp)
            activated_starcks.append(unconfirmed[itracked])
        for it in u_unconfirmed:
            track = unconfirmed[it]
            track.mark_removed()
            removed_stracks.append(track)

        """ Step 4: Init new stracks"""
        for inew in u_detection:
            track = detections[inew]
            if track.score < self.det_thresh:
                continue
            assigned_track_id = (
                self.track_id_allocator()
                if callable(self.track_id_allocator)
                else None
            )
            track.activate(
                self.kalman_filter,
                self.frame_id,
                timestamp=timestamp,
                track_id=assigned_track_id,
            )
            activated_starcks.append(track)
        """ Step 5: Update state"""
        for track in self.lost_stracks:
            timed_out = (
                self.max_lost_sec is not None
                and timestamp is not None
                and track.last_seen_timestamp is not None
                and timestamp - track.last_seen_timestamp > self.max_lost_sec
            )
            frame_timed_out = self.frame_id - track.end_frame > self.max_time_lost
            if timed_out or (self.max_lost_sec is None and frame_timed_out):
                track.mark_removed()
                removed_stracks.append(track)

        self.tracked_stracks = [t for t in self.tracked_stracks if t.state == TrackState.Tracked]
        self.tracked_stracks = joint_stracks(self.tracked_stracks, activated_starcks)
        self.tracked_stracks = joint_stracks(self.tracked_stracks, refind_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.tracked_stracks)
        self.lost_stracks.extend(lost_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.removed_stracks)
        self.removed_stracks.extend(removed_stracks)
        self.tracked_stracks, self.lost_stracks = remove_duplicate_stracks(self.tracked_stracks, self.lost_stracks)
        # get scores of lost tracks
        output_stracks = [track for track in self.tracked_stracks if track.is_activated]

        return output_stracks


def joint_stracks(tlista, tlistb):
    exists = {}
    res = []
    for t in tlista:
        exists[t.track_id] = 1
        res.append(t)
    for t in tlistb:
        tid = t.track_id
        if not exists.get(tid, 0):
            exists[tid] = 1
            res.append(t)
    return res


def sub_stracks(tlista, tlistb):
    stracks = {}
    for t in tlista:
        stracks[t.track_id] = t
    for t in tlistb:
        tid = t.track_id
        if stracks.get(tid, 0):
            del stracks[tid]
    return list(stracks.values())


def remove_duplicate_stracks(stracksa, stracksb):
    pdist = matching.iou_distance(stracksa, stracksb)
    pairs = np.where(pdist < 0.15)
    dupa, dupb = list(), list()
    for p, q in zip(*pairs):
        timep = stracksa[p].frame_id - stracksa[p].start_frame
        timeq = stracksb[q].frame_id - stracksb[q].start_frame
        if timep > timeq:
            dupb.append(q)
        else:
            dupa.append(p)
    resa = [t for i, t in enumerate(stracksa) if i not in dupa]
    resb = [t for i, t in enumerate(stracksb) if i not in dupb]
    return resa, resb
