"""Disk-backed, source-watermarked mutual-unique association of ended segments.

The worker retains one bounded descriptor batch. Open candidates block a decision;
late completion can delay a relation, never the publication of original segments.
"""

from contextlib import contextmanager
import json
import logging
import sqlite3
import threading

from services.MissionTrajectoryArchive import _merge_candidate
from utils_local.runtime_logging import stage

LOG = logging.getLogger(__name__)


class StreamingRelations:
    def __init__(self, archive, mission_id, publish, *, batch_size=32):
        self.archive, self.mission_id, self.publish = archive, mission_id, publish
        self.batch_size = batch_size
        self.path = archive._mission_dir(mission_id) / "streaming-relations.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.wake, self.stopping = threading.Event(), threading.Event()
        self.thread, self.error = None, None
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id TEXT PRIMARY KEY, start REAL, last REAL, state TEXT,
                    descriptor TEXT, encoded INTEGER DEFAULT 0, settled INTEGER DEFAULT 0, retry_after REAL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS tracks_start ON tracks(start);
                CREATE INDEX IF NOT EXISTS tracks_end ON tracks(last);
                CREATE INDEX IF NOT EXISTS tracks_jobs ON tracks(state,encoded,settled,last);
                CREATE TABLE IF NOT EXISTS clock (id INTEGER PRIMARY KEY, source_time REAL);
                INSERT OR IGNORE INTO clock VALUES (1,-1);
                CREATE TABLE IF NOT EXISTS outbox (
                    predecessor TEXT PRIMARY KEY, successor TEXT UNIQUE, evidence TEXT, published INTEGER DEFAULT 0);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def check(self):
        if self.error is not None:
            raise RuntimeError("streaming relation worker failed") from self.error

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(
                target=self.run, name="streaming-relations", daemon=True
            )
            self.thread.start()

    def run(self):
        try:
            while not self.stopping.is_set():
                if not self.process_once():
                    self.wake.wait(0.5)
                    self.wake.clear()
        except BaseException as error:
            self.error = error
            LOG.exception("STREAMING_RELATIONS_FAILED mission=%s", self.mission_id)

    def observe(self, tracks, *, source_time, closing=()):
        self.check()
        rows = [
            (str(t.id), float(t.timestamp_first), float(t.timestamp_last))
            for t in tracks
        ]
        with self.db() as db:
            old = db.execute("SELECT source_time FROM clock WHERE id=1").fetchone()[0]
            if source_time < old:
                raise ValueError("relation source watermark regressed")
            # First write acquires SQLite's writer lock; keep the original
            # transaction mode and measure this call without changing scheduling.
            with stage("egress.relations_lock_wait"):
                db.execute("UPDATE clock SET source_time=? WHERE id=1", (source_time,))
            db.execute("CREATE TEMP TABLE current_ids (id TEXT PRIMARY KEY)")
            db.executemany(
                "INSERT INTO current_ids VALUES (?)", ((row[0],) for row in rows)
            )
            db.executemany(
                "INSERT INTO tracks(id,start,last,state) VALUES (?,?,?,'active') ON CONFLICT(id) DO UPDATE SET last=excluded.last WHERE tracks.state='active'",
                rows,
            )
            for segment in closing:
                key = str(segment["track_id"])
                times = segment["trajectory_timestamps_sec"]
                db.execute(
                    "INSERT INTO tracks(id,start,last,state) VALUES (?,?,?,'closing') ON CONFLICT(id) DO UPDATE SET state='closing',last=excluded.last WHERE tracks.state IN ('active','discarded')",
                    (key, times[0], times[-1]),
                )
            # Absence becomes terminal only after the original tracker has removed
            # the ID from its buffer (which already includes the lost grace period).
            db.execute(
                "UPDATE tracks SET state='discarded' WHERE state='active' AND NOT EXISTS (SELECT 1 FROM current_ids c WHERE c.id=tracks.id)"
            )
        self.wake.set()

    def closed(self, segment):
        self.check()
        descriptor = {
            k: segment.get(k)
            for k in ("track_id", "appearance_embedding", "appearance_crop_jpeg")
        }
        for field in ("trajectory_timestamps_sec", "trajectory_enu_m", "trajectory_px"):
            descriptor[field] = [segment[field][0], segment[field][-1]]
        start, last = descriptor["trajectory_timestamps_sec"]
        raw = json.dumps(descriptor, sort_keys=True)
        with self.db() as db:
            existing = db.execute(
                "SELECT descriptor FROM tracks WHERE id=?", (str(segment["track_id"]),)
            ).fetchone()
            if existing and existing[0] is not None:
                # Encoded descriptors are immutable derivations; a duplicate raw
                # submission must not reset their job or override a frozen edge.
                return
            db.execute(
                "INSERT INTO tracks(id,start,last,state,descriptor) VALUES (?,?,?,'closed',?) ON CONFLICT(id) DO UPDATE SET state='closed',last=excluded.last,descriptor=excluded.descriptor",
                (str(segment["track_id"]), start, last, raw),
            )
            db.execute(
                "UPDATE tracks SET retry_after=0 WHERE last>=? AND last<?",
                (start - 2, start),
            )
        self.wake.set()

    @staticmethod
    def best(db, descriptor, direction):
        if direction == "successor":
            end = descriptor["trajectory_timestamps_sec"][-1]
            rows = db.execute(
                "SELECT id,descriptor FROM tracks WHERE state='closed' AND start>? AND start<=?",
                (end, end + 2),
            )
        else:
            start = descriptor["trajectory_timestamps_sec"][0]
            rows = db.execute(
                "SELECT id,descriptor FROM tracks WHERE state='closed' AND last<? AND last>=?",
                (start, start - 2),
            )
        best = []
        for key, raw in rows:
            other = json.loads(raw)
            evidence = (
                _merge_candidate(descriptor, other)
                if direction == "successor"
                else _merge_candidate(other, descriptor)
            )
            if evidence:
                best.append((evidence["score"], key, evidence))
                best.sort(key=lambda v: (-v[0], v[1]))
                del best[2:]
        if not best or (len(best) > 1 and best[0][0] - best[1][0] < 0.05):
            return None
        return best[0]

    def process_once(self):
        work = False
        # Model loading/embedding happens here, outside the frame/track process.
        with self.db() as db:
            jobs = db.execute(
                "SELECT id,descriptor FROM tracks WHERE state='closed' AND encoded=0 ORDER BY last LIMIT ?",
                (self.batch_size,),
            ).fetchall()
        descriptors = [json.loads(raw) for _, raw in jobs]
        need = [d for d in descriptors if not d.get("appearance_embedding")]
        if need:
            self.archive._encode_appearance(need)
        with self.db() as db:
            for (key, _), descriptor in zip(jobs, descriptors):
                descriptor.pop("appearance_crop_jpeg", None)
                db.execute(
                    "UPDATE tracks SET descriptor=?,encoded=1 WHERE id=?",
                    (json.dumps(descriptor), key),
                )
            work = bool(jobs)
            watermark = db.execute(
                "SELECT source_time FROM clock WHERE id=1"
            ).fetchone()[0]
            lefts = db.execute(
                "SELECT id,last,descriptor FROM tracks WHERE state='closed' AND encoded=1 AND settled=0 AND last+2<? AND retry_after<=? ORDER BY last LIMIT ?",
                (watermark, watermark, self.batch_size),
            ).fetchall()
            for key, end, raw in lefts:
                # Wait for every possible successor, including long-lived ones,
                # and for each ended candidate's descriptor extraction.
                unresolved = db.execute(
                    "SELECT 1 FROM tracks WHERE start>? AND start<=? AND (state IN ('active','closing') OR (state='closed' AND encoded=0)) LIMIT 1",
                    (end, end + 2),
                ).fetchone()
                if unresolved:
                    db.execute(
                        "UPDATE tracks SET retry_after=? WHERE id=?",
                        (watermark + 0.5, key),
                    )
                    work = True
                    continue
                left = json.loads(raw)
                successor = self.best(db, left, "successor")
                if successor:
                    _, right_id, evidence = successor
                    right = json.loads(
                        db.execute(
                            "SELECT descriptor FROM tracks WHERE id=?", (right_id,)
                        ).fetchone()[0]
                    )
                    start = right["trajectory_timestamps_sec"][0]
                    unresolved = db.execute(
                        "SELECT 1 FROM tracks WHERE last<? AND last>=? AND (state IN ('active','closing') OR (state='closed' AND encoded=0)) LIMIT 1",
                        (start, start - 2),
                    ).fetchone()
                    if unresolved:
                        db.execute(
                            "UPDATE tracks SET retry_after=? WHERE id=?",
                            (watermark + 0.5, key),
                        )
                        work = True
                        continue
                    predecessor = self.best(db, right, "predecessor")
                    if predecessor and predecessor[1] == key:
                        evidence = {k: v for k, v in evidence.items() if k != "score"}
                        db.execute(
                            "INSERT OR IGNORE INTO outbox(predecessor,successor,evidence) VALUES (?,?,?)",
                            (key, right_id, json.dumps(evidence)),
                        )
                db.execute("UPDATE tracks SET settled=1 WHERE id=?", (key,))
                work = True
            pending = db.execute(
                "SELECT predecessor,successor,evidence FROM outbox WHERE published=0 LIMIT ?",
                (self.batch_size,),
            ).fetchall()
        for predecessor, successor, evidence in pending:
            self.publish(predecessor, successor, json.loads(evidence))
            with self.db() as db:
                db.execute(
                    "UPDATE outbox SET published=1 WHERE predecessor=?", (predecessor,)
                )
            work = True
        return work

    def finish(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=120)
            if self.thread.is_alive():
                raise TimeoutError("relation worker did not drain")
        self.check()
        with self.db() as db:
            end = db.execute("SELECT coalesce(max(last),0) FROM tracks").fetchone()[0]
            db.execute("UPDATE clock SET source_time=? WHERE id=1", (end + 3,))
            db.execute(
                "UPDATE tracks SET state='discarded' WHERE state IN ('active','closing')"
            )
            db.execute("UPDATE tracks SET retry_after=0")
        while self.process_once():
            pass
